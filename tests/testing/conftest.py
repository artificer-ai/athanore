"""A store, one attempt's :class:`TaskContext` over it, and the agent API.

The doubles of :mod:`athanore.testing` do their work *through* a context —
they declare an output model on it, append to its work log, record a
stats entry against its task — so testing them needs the same thing an
agent-façade test needs: real services over a real SQLite file, and no
scheduler anywhere near it. ``tests/agents/conftest.py`` builds the same
context for the same reason; ``tests`` is not a package, so a fixture
shared between two suites arrives through pytest or is written twice
(D112).

Two fixtures rather than one, and the split is the same one the agents
suite draws. :func:`context` is an attempt with services over the store,
which is all a ``log=``, ``stream=`` or ``stats=`` double touches.
:func:`served_context` is an attempt that a **real** ``create_app()`` is
listening for on loopback: its task is claimed so its token is live, it
is registered on the engine's live registry the way the runner registers
one, and ``api_base`` is the port the application is on. That is what
``MockAgent(submit=…)`` needs, because a submission is an HTTP POST to
``/api/agent/tasks/{id}/submit`` with the task token and nothing about it
is faked (T045).

``tests/testing/test_fake_acp.py`` needs none of this — the fake is a
subprocess and its subject is the wire — so nothing here is imported by
it.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from fastapi import FastAPI

from athanore.api.app import create_app
from athanore.engine import Engine
from athanore.engine.context import TaskContext
from athanore.engine.services import TaskServices
from athanore.events.bus import EventBus
from athanore.settings import AthanoreSettings
from athanore.store.engine import make_engine
from athanore.store.tables import metadata
from athanore.store.uow import Store

API_BASE = "http://127.0.0.1:4002"
TOKEN = "tok-fdb0a1c2e3f4"
WORKFLOW = "demo"
NODE = "build"
FLUSH_INTERVAL = 0.02


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    return f"sqlite+aiosqlite:///{tmp_path / 'athanore.db'}"


@pytest.fixture
async def store(db_url: str, bus: EventBus) -> AsyncIterator[Store]:
    engine = make_engine(db_url)
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    try:
        yield Store(engine, bus)
    finally:
        await engine.dispose()


@pytest.fixture
def settings(tmp_path: Path, db_url: str) -> AthanoreSettings:
    """A loopback bind pinned to this test's database.

    ``root_path`` matters: without it the application would read the
    developer's own token file when it decided whether auth is on.
    """

    return AthanoreSettings(
        root_path=tmp_path,
        db_url=db_url,
        public_url=API_BASE,
        workers=1,
    )


@pytest.fixture
def engine(settings: AthanoreSettings, store: Store, bus: EventBus) -> Engine:
    """An engine with nothing registered and no loop running.

    It is here for its :class:`~athanore.engine.live.LiveRegistry`: the
    agent endpoints answer 409 for a task no attempt of this process is
    running, and :func:`served_context` registers its attempt exactly as
    the runner would.
    """

    return Engine(settings, store, bus)


@pytest.fixture
def context(store: Store) -> Callable[..., Awaitable[TaskContext]]:
    """The context of one attempt of a real run's one task."""

    async def make(
        title: str = "a run", *, attempt: int = 1, api_base: str = API_BASE
    ) -> TaskContext:
        async with store.uow() as uow:
            run = await uow.runs.insert(WORKFLOW, title)
            task = await uow.tasks.enqueue(
                run.id, NODE, None, priority=0, explicit=False
            )
        return TaskContext(
            run_id=run.id,
            task_id=task.id,
            workflow=WORKFLOW,
            node=NODE,
            attempt=attempt,
            token=TOKEN,
            api_base=api_base,
            services=_services(store, run.id, task.id),
        )

    return make


@pytest.fixture
async def agent_api(
    settings: AthanoreSettings, engine: Engine, store: Store
) -> AsyncIterator[str]:
    """The real application, listening on loopback; its base URL.

    ``create_app()`` as every host builds it, over this test's store and
    engine, so the double posts to the endpoint of 08 and not to a
    stand-in for it.
    """

    app = create_app(settings=settings, engine=engine, store=store)
    with _uvicorn_logging_restored():
        server, serving, port = await _serve(app)
        try:
            yield f"http://127.0.0.1:{port}"
        finally:
            server.should_exit = True
            await asyncio.wait_for(serving, timeout=10)


@pytest.fixture
def served_context(
    store: Store, engine: Engine, agent_api: str
) -> Callable[..., Awaitable[TaskContext]]:
    """A **claimed** attempt whose ``api_base`` is a listening agent API.

    Claimed, because a task token is minted at claim and is valid only
    while the attempt is ``in_progress`` or ``waiting`` (12 §Task
    tokens); registered on ``engine.live``, because the submit endpoint
    reads the declared ``output_model`` off the live context and answers
    409 when there is none. Both are what the runner does, done here by
    hand: this suite has no scheduler.
    """

    async def make(title: str = "a run", *, attempt: int = 1) -> TaskContext:
        async with store.uow() as uow:
            run = await uow.runs.insert(WORKFLOW, title)
            task = await uow.tasks.enqueue(
                run.id, NODE, None, priority=0, explicit=False
            )
            claimed = await uow.tasks.claim_ready(1, [WORKFLOW])
        ctx = TaskContext(
            run_id=run.id,
            task_id=task.id,
            workflow=WORKFLOW,
            node=NODE,
            attempt=attempt,
            token=claimed[0].token,
            api_base=agent_api,
            services=_services(store, run.id, task.id),
        )
        engine.live.register(ctx)
        return ctx

    return make


def _services(store: Store, run_id: str, task_id: int) -> TaskServices:
    """The bundle the runner builds per attempt (04 §TaskContext)."""

    return TaskServices(
        store,
        run_id=run_id,
        task_id=task_id,
        node=NODE,
        workflow=WORKFLOW,
        flush_interval=FLUSH_INTERVAL,
    )


async def _serve(app: FastAPI) -> tuple[uvicorn.Server, asyncio.Task[None], int]:
    """Serve ``app`` on a free loopback port; a client reaches it by URL."""

    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=0,
            log_level="warning",
            log_config=None,
            lifespan="on",
        )
    )
    serving = asyncio.get_running_loop().create_task(server.serve())
    while not server.started:  # noqa: ASYNC110 - uvicorn signals with a flag
        await asyncio.sleep(0.01)
    port: int = server.servers[0].sockets[0].getsockname()[1]
    return server, serving, port


@contextmanager
def _uvicorn_logging_restored() -> Iterator[None]:
    """Put the ``uvicorn.*`` loggers back the way they were found.

    ``uvicorn.Config`` configures logging **globally**, and this suite
    starts a server per test; left alone it would leak into whatever ran
    next (the reason ``tests/agents/conftest.py`` does the same).
    """

    names = ("uvicorn", "uvicorn.error", "uvicorn.access", "uvicorn.asgi")
    before: list[tuple[logging.Logger, int, list[Any], bool]] = [
        (logger, logger.level, list(logger.handlers), logger.propagate)
        for logger in (logging.getLogger(name) for name in names)
    ]
    try:
        yield
    finally:
        for logger, level, handlers, propagate in before:
            logger.setLevel(level)
            logger.handlers = handlers
            logger.propagate = propagate

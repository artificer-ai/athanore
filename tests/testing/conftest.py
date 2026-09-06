"""A store, and one attempt's :class:`TaskContext` over it.

The doubles of :mod:`athanore.testing` do their work *through* a context —
they declare an output model on it, append to its work log, record a
stats entry against its task — so testing them needs the same thing an
agent-façade test needs: real services over a real SQLite file, and no
scheduler anywhere near it. ``tests/agents/conftest.py`` builds the same
context for the same reason; ``tests`` is not a package, so a fixture
shared between two suites arrives through pytest or is written twice
(D112).

``tests/testing/test_fake_acp.py`` needs none of this — the fake is a
subprocess and its subject is the wire — so nothing here is imported by
it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path

import pytest

from athanore.engine.context import TaskContext
from athanore.engine.services import TaskServices
from athanore.events.bus import EventBus
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
async def store(tmp_path: Path, bus: EventBus) -> AsyncIterator[Store]:
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'athanore.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    try:
        yield Store(engine, bus)
    finally:
        await engine.dispose()


@pytest.fixture
def context(store: Store) -> Callable[..., Awaitable[TaskContext]]:
    """The context of one attempt of a real run's one task."""

    async def make(title: str = "a run", *, attempt: int = 1) -> TaskContext:
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
            api_base=API_BASE,
            services=TaskServices(
                store,
                run_id=run.id,
                task_id=task.id,
                node=NODE,
                workflow=WORKFLOW,
                flush_interval=FLUSH_INTERVAL,
            ),
        )

    return make

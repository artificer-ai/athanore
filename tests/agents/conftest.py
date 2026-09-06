"""A store, and one attempt's :class:`TaskContext` over it.

The agent suite's subject is the façade, not the engine: nothing here
runs a scheduler, claims a task or holds a pool slot. What a façade needs
is a context — the ids that go into 19's kickoff, the token that goes
into its curl lines, and ``services`` for the one read the prompt makes
(the run's title, 04 §TaskContext).

The store is real rather than a stub for that read. A fake ``run.get()``
would let the title be anything, and the thing worth asserting is that
the title in the prompt is the title of the run the operator submitted.
It is a file on ``tmp_path`` and SQLite only, for the reason
``tests/engine/conftest.py`` gives: the backend matrix belongs to the
suite that owns the SQL.

A conftest rather than imports because ``tests`` is not a package, so a
helper shared between this suite's modules arrives through pytest or not
at all (D112).
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

#: What ``settings.public_url`` is in these tests: the loopback bind an
#: agent on the same machine is told to call (08 §Agent).
API_BASE = "http://127.0.0.1:4002"

#: A task token, clear text. Distinctive enough that a test can look for
#: it anywhere in a rendered prompt and mean it.
TOKEN = "tok-fdb0a1c2e3f4"

WORKFLOW = "demo"
NODE = "build"
FLUSH_INTERVAL = 0.05


@pytest.fixture
def bus() -> EventBus:
    """The bus the store publishes to. Nothing here subscribes to it."""

    return EventBus()


@pytest.fixture
async def store(tmp_path: Path, bus: EventBus) -> AsyncIterator[Store]:
    """A store on an empty SQLite file."""

    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'athanore.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    try:
        yield Store(engine, bus)
    finally:
        await engine.dispose()


@pytest.fixture
def context(store: Store) -> Callable[..., Awaitable[TaskContext]]:
    """Make the context of one attempt of a real run's one task.

    The run and the task are rows: the prompt reads the run back through
    ``services.run.get()``, and a context pointing at a run that does not
    exist would be a fixture that only ever tested the failure.
    """

    async def make(
        title: str = "a run",
        *,
        node: str = NODE,
        api_base: str = API_BASE,
        token: str = TOKEN,
    ) -> TaskContext:
        async with store.uow() as uow:
            run = await uow.runs.insert(WORKFLOW, title)
            task = await uow.tasks.enqueue(
                run.id, node, None, priority=0, explicit=False
            )
        return TaskContext(
            run_id=run.id,
            task_id=task.id,
            workflow=WORKFLOW,
            node=node,
            attempt=1,
            token=token,
            api_base=api_base,
            services=TaskServices(
                store,
                run_id=run.id,
                task_id=task.id,
                node=node,
                workflow=WORKFLOW,
                flush_interval=FLUSH_INTERVAL,
            ),
        )

    return make

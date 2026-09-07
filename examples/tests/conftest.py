"""What an example needs to be tested against a real task.

The examples are outside the package but they are not outside the
contract: an example agent renders the same prompt, through the same
:class:`~athanore.engine.context.TaskContext`, as one written in a
workflow. So this is the agent suite's context fixture, kept small — a
store on a file and one task of one run — because what these tests assert
is what an example *declares*, not what the engine does with it.

A conftest rather than imports: ``examples/tests`` is not a package, so
anything shared between its modules arrives through pytest or not at all
(D112).
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

#: A task token, clear text and distinctive, so a test can look for it
#: anywhere in a rendered prompt and mean it.
TOKEN = "tok-3f9c1ab27e40"

WORKFLOW = "demo"
NODE = "build"


@pytest.fixture
async def store(tmp_path: Path) -> AsyncIterator[Store]:
    """A store on an empty SQLite file."""

    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'athanore.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    try:
        yield Store(engine, EventBus())
    finally:
        await engine.dispose()


@pytest.fixture
def context(store: Store) -> Callable[..., Awaitable[TaskContext]]:
    """The context of one attempt of a real run's one task.

    The run and the task are rows because the prompt reads the run back
    through ``services.run.get()`` for 19's kickoff line: a context
    pointing at a run that does not exist would only ever test the
    failure.
    """

    async def make(title: str = "a run", *, node: str = NODE) -> TaskContext:
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
            token=TOKEN,
            api_base=API_BASE,
            services=TaskServices(
                store,
                run_id=run.id,
                task_id=task.id,
                node=node,
                workflow=WORKFLOW,
                flush_interval=0.05,
            ),
        )

    return make

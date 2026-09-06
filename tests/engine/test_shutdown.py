"""Stopping the engine, and starting it again afterwards (T027, 04 §Shutdown).

The contract is one round trip rather than two halves, so that is what
this file asserts: an attempt interrupted by ``stop()`` is picked up by
the next ``start()`` and finishes. Between the two, three things have to
be true, and each is one step of 04 §Shutdown:

- ``engine.stopping {task_ids}`` names what was interrupted, because no
  row will carry that fact;
- the task row is left ``in_progress`` — a graceful stop writes no task
  status, so a crash and a clean exit leave the same store (D52) and
  ``cancelled`` keeps meaning operator intent;
- the pool slot comes back, the loop is gone, and stopping twice is not
  an error.
"""

from __future__ import annotations

import asyncio

from athanore.engine import Engine
from athanore.engine.pools import Pool
from athanore.events.names import EventName
from athanore.store.rows import EventRow, RunStatus, TaskStatus
from athanore.store.uow import Store
from athanore.workflow import Workflow

# --------------------------------------------------------------------------
# A workflow that parks in its body until it is let go
# --------------------------------------------------------------------------


class Sleeper:
    """A node body that says when it started and then waits to be cancelled.

    ``finished`` is set only by a body that ran to the end, which is what
    makes "the second engine finished the work" an assertion rather than
    an inference from the row.
    """

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.finished = asyncio.Event()
        self.runs = 0
        #: Set once the test wants the body to return rather than sleep.
        self.release = False

    def workflow(self, name: str = "sleepy") -> Workflow:
        wf = Workflow(name)

        @wf.node(start=True)
        async def only() -> str:
            self.runs += 1
            self.started.set()
            if not self.release:
                # Far longer than the test: the only way out is the
                # cancellation `stop()` sends.
                await asyncio.sleep(3600)
            self.finished.set()
            return "landed"

        return wf


async def submit(store: Store, workflow: str, node: str = "only") -> tuple[str, int]:
    """A queued run with one ready task; its run id and task id."""

    async with store.uow() as uow:
        run = await uow.runs.insert(workflow, "a run")
        task = await uow.tasks.enqueue(run.id, node, None, 0, False)
    return run.id, task.id


async def status_of(store: Store, task_id: int) -> TaskStatus:
    async with store.reader() as reader:
        row = await reader.tasks.get(task_id)
    assert row is not None
    return row.status


async def run_status(store: Store, run_id: str) -> RunStatus:
    async with store.reader() as reader:
        row = await reader.runs.get(run_id)
    assert row is not None
    return row.status


async def stopping_events(store: Store) -> list[EventRow]:
    async with store.reader() as reader:
        rows = await reader.events.list_after(0, 1000)
    return [row for row in rows if row.name == EventName.engine_stopping]


# --------------------------------------------------------------------------
# The round trip
# --------------------------------------------------------------------------


async def test_stop_interrupts_a_body_and_the_next_start_recovers_it(
    engines, store: Store, wait_for, wait_until
) -> None:
    """The whole of 04 §Shutdown and §Recovery, as one story.

    A body is inside its ``sleep`` when the engine stops; the shutdown
    announces it, leaves its row alone and lets the process go. A second
    engine — the restart — resets that row and runs it to completion.
    """

    sleeper = Sleeper()
    first: Engine = engines()
    first.register(sleeper.workflow().finalize(), Pool("test", 1))
    run_id, task_id = await submit(store, "sleepy")

    await first.start()
    await wait_for(sleeper.started)
    await first.stop()

    (event,) = await stopping_events(store)
    assert event.data == {"task_ids": [task_id]}
    assert event.run_id is None, "engine.* events carry no run"
    assert await status_of(store, task_id) is TaskStatus.in_progress, (
        "a graceful stop writes no task status (D52)"
    )
    assert first.pools.get("test").free() == 1, "the slot came back"
    assert first.scheduler.in_flight == ()

    sleeper.release = True
    second: Engine = engines()
    second.register(sleeper.workflow().finalize(), Pool("test", 1))
    await second.start()

    await wait_for(sleeper.finished)
    await wait_until(lambda: _completed(store, run_id))
    assert sleeper.runs == 2, "the interrupted attempt re-executed from scratch"
    assert await status_of(store, task_id) is TaskStatus.done


# --------------------------------------------------------------------------
# The steps of it, separately
# --------------------------------------------------------------------------


async def test_stopping_names_every_attempt_that_was_in_flight(
    engines, store: Store, wait_until
) -> None:
    """One event, one transaction, both ids — not one event per attempt."""

    sleeper = Sleeper()
    engine: Engine = engines()
    engine.register(sleeper.workflow().finalize(), Pool("test", 2))
    _, first = await submit(store, "sleepy")
    _, second = await submit(store, "sleepy")

    await engine.start()
    await wait_until(lambda: _in_flight(engine, 2))
    await engine.stop()

    (event,) = await stopping_events(store)
    assert sorted(event.data["task_ids"]) == sorted([first, second])


async def test_a_quiet_shutdown_announces_nothing(engines, store: Store) -> None:
    """Nothing was interrupted, so there is nothing to record."""

    engine: Engine = engines()
    engine.register(Sleeper().workflow().finalize(), Pool("test", 1))

    await engine.start()
    await engine.stop()

    assert await stopping_events(store) == []


async def test_stopping_twice_is_not_an_error(engines, store: Store) -> None:
    """Test teardown, a signal and an exiting host can all arrive together."""

    engine: Engine = engines()
    engine.register(Sleeper().workflow().finalize(), Pool("test", 1))

    await engine.start()
    await engine.stop()
    await engine.stop()

    assert not engine.scheduler.running


async def test_stopping_an_engine_that_never_started_is_a_no_op(
    engines, store: Store
) -> None:
    """A host that fails before ``start()`` still runs its ``finally``."""

    engine: Engine = engines()

    await engine.stop()

    assert not engine.scheduler.running
    assert await stopping_events(store) == []


async def test_a_stopped_engine_claims_nothing_more(
    engines, store: Store, wait_for
) -> None:
    """Step 1 is "stop claiming", and it is what makes the rest hold.

    A task enqueued after the stop stays ``ready``: the loop is gone, and
    nothing else in the engine claims.
    """

    sleeper = Sleeper()
    sleeper.release = True
    engine: Engine = engines()
    engine.register(sleeper.workflow().finalize(), Pool("test", 1))
    await submit(store, "sleepy")

    await engine.start()
    await wait_for(sleeper.finished)
    await engine.stop()

    _, late = await submit(store, "sleepy")
    engine.notify()
    await asyncio.sleep(0.1)

    assert await status_of(store, late) is TaskStatus.ready
    assert sleeper.runs == 1


async def _completed(store: Store, run_id: str) -> bool:
    return await run_status(store, run_id) is RunStatus.completed


async def _in_flight(engine: Engine, count: int) -> bool:
    return len(engine.scheduler.in_flight) == count

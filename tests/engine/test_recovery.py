"""What startup does about the last process's attempts (T027, 04 §Recovery).

Three facts, and each of them is a decision that could have gone the
other way:

- an interrupted attempt — ``in_progress`` or ``waiting`` — goes back to
  ``ready`` with its token hash cleared, because the attempt re-executes
  from scratch and the token it authenticated with died with it (D38);
- ``engine.recovered`` lists exactly those ids, so the interruption is in
  the audit trail rather than only in the rows;
- a run whose workflow is not registered here is **untouched**, and never
  claimed. Resetting it would make it ``ready`` forever, since no pool
  can claim a workflow this server does not have.

The last one is asserted twice over: the row is unchanged, and the engine
is then run for long enough to claim it if it were going to.

The same sweep runs for one name after start — ``recover(engine,
[name])``, what a workflow added to a running server gets (22 §Add step
3, T083). What is new there is that this process may already be running
attempts of the name: those rows are excluded, and the sweep runs
between ticks so the exclusion is exact.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from athanore.engine import Engine
from athanore.engine.pools import Pool
from athanore.engine.recovery import recover
from athanore.events.names import EventName
from athanore.store.rows import EventRow, TaskRow, TaskStatus
from athanore.store.tables import tasks
from athanore.store.uow import Store
from athanore.workflow import Workflow

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def workflow(name: str = "recovered") -> Workflow:
    """A one-node workflow whose body records that it ran."""

    wf = Workflow(name)

    @wf.node(start=True)
    async def only() -> str:
        return "done"

    return wf


async def submit(store: Store, workflow_name: str, node: str = "only") -> int:
    """A queued run of ``workflow_name`` with one ready task; its task id."""

    async with store.uow() as uow:
        run = await uow.runs.insert(workflow_name, "a run")
        task = await uow.tasks.enqueue(run.id, node, None, 0, False)
    return task.id


async def force(store: Store, task_id: int, **values: Any) -> None:
    """Write columns straight onto a task, as a dead process left them."""

    async with store.uow() as uow:
        await uow.conn.execute(
            tasks.update().where(tasks.c.id == task_id).values(values)
        )


async def status_of(store: Store, task_id: int) -> TaskStatus:
    async with store.reader() as reader:
        row = await reader.tasks.get(task_id)
    assert row is not None
    return row.status


async def token_hash_of(store: Store, task_id: int) -> str | None:
    """The stored hash, which ``TaskRow`` deliberately does not expose."""

    async with store.read() as conn:
        result = await conn.execute(tasks.select().where(tasks.c.id == task_id))
        row = result.mappings().one()
    return row["token_hash"]


async def engine_events(store: Store, name: EventName) -> list[EventRow]:
    """The stored ``engine.*`` events, which carry no ``run_id``."""

    async with store.reader() as reader:
        rows = await reader.events.list_after(0, 1000)
    return [row for row in rows if row.name == name]


# --------------------------------------------------------------------------
# The reset
# --------------------------------------------------------------------------


async def test_interrupted_attempts_go_back_to_ready_with_no_token(
    engines, store: Store
) -> None:
    """Both interrupted statuses reset; the dead attempt's token dies too."""

    engine: Engine = engines()
    engine.register(workflow().finalize(), Pool("test", 1))
    interrupted = await submit(store, "recovered")
    parked = await submit(store, "recovered")
    await force(
        store,
        interrupted,
        status=TaskStatus.in_progress.value,
        token_hash="a" * 64,
    )
    await force(store, parked, status=TaskStatus.waiting.value, token_hash="b" * 64)

    task_ids = await recover(engine)

    assert task_ids == sorted([interrupted, parked])
    assert await status_of(store, interrupted) is TaskStatus.ready
    assert await status_of(store, parked) is TaskStatus.ready
    assert await token_hash_of(store, interrupted) is None
    assert await token_hash_of(store, parked) is None


async def test_recovery_announces_exactly_the_ids_it_reset(
    engines, store: Store
) -> None:
    """`engine.recovered` is the audit trail of the interruption (18)."""

    engine: Engine = engines()
    engine.register(workflow().finalize(), Pool("test", 1))
    interrupted = await submit(store, "recovered")
    finished = await submit(store, "recovered")
    await force(store, interrupted, status=TaskStatus.in_progress.value)
    await force(store, finished, status=TaskStatus.done.value)

    await recover(engine)

    (event,) = await engine_events(store, EventName.engine_recovered)
    assert event.data == {"task_ids": [interrupted]}
    assert event.run_id is None, "engine.* events carry no run"
    assert await status_of(store, finished) is TaskStatus.done


async def test_a_quiet_startup_announces_nothing(engines, store: Store) -> None:
    """An event saying nothing was recovered is noise in every timeline."""

    engine: Engine = engines()
    engine.register(workflow().finalize(), Pool("test", 1))
    await submit(store, "recovered")

    assert await recover(engine) == []
    assert await engine_events(store, EventName.engine_recovered) == []


# --------------------------------------------------------------------------
# Unregistered workflows
# --------------------------------------------------------------------------


async def test_a_run_of_an_unregistered_workflow_is_untouched_and_never_claimed(
    engines, store: Store, wait_until
) -> None:
    """Rule 2 of 04 §Recovery, asserted both ways.

    The row keeps the status the dead process left, and an engine running
    long enough to have claimed it — the registered run beside it
    completes, which cannot happen without a tick that gave every pool
    its turn — never does.
    """

    engine: Engine = engines()
    engine.register(workflow("registered").finalize(), Pool("test", 1))
    orphan = await submit(store, "gone_away")
    await force(store, orphan, status=TaskStatus.in_progress.value)
    live = await submit(store, "registered")

    await engine.start()

    await wait_until(lambda: _is_done(store, live))
    assert await status_of(store, orphan) is TaskStatus.in_progress
    assert await engine_events(store, EventName.engine_recovered) == []


async def test_an_unregistered_run_recovers_once_its_workflow_is_back(
    engines, store: Store
) -> None:
    """The parked row is not lost: registering the code recovers it.

    Which is the whole reason recovery leaves it alone rather than
    cancelling it — the workflow is missing from *this* process, not from
    the world.
    """

    engine: Engine = engines()
    engine.register(workflow("registered").finalize(), Pool("test", 1))
    orphan = await submit(store, "recovered")
    await force(store, orphan, status=TaskStatus.waiting.value)

    await recover(engine)
    assert await status_of(store, orphan) is TaskStatus.waiting

    restarted: Engine = engines()
    restarted.register(workflow().finalize(), Pool("test", 1))
    assert await recover(restarted) == [orphan]
    assert await status_of(store, orphan) is TaskStatus.ready


# --------------------------------------------------------------------------
# Recovery is what `start()` does first
# --------------------------------------------------------------------------


async def test_start_recovers_before_it_claims(
    engines, store: Store, wait_until
) -> None:
    """An interrupted row is picked up by the engine that starts next.

    Started the other way round the loop could claim a row recovery was
    about to rewrite, so the assertion is the round trip: an
    ``in_progress`` row with a stale token becomes a completed attempt
    with no operator doing anything.
    """

    engine: Engine = engines()
    engine.register(workflow().finalize(), Pool("test", 1))
    interrupted = await submit(store, "recovered")
    await force(
        store,
        interrupted,
        status=TaskStatus.in_progress.value,
        token_hash="c" * 64,
    )

    await engine.start()

    await wait_until(lambda: _is_done(store, interrupted))
    assert await token_hash_of(store, interrupted) is not None, (
        "the fresh claim mints a token of its own"
    )
    assert await token_hash_of(store, interrupted) != "c" * 64


async def _is_done(store: Store, task_id: int) -> bool:
    return await status_of(store, task_id) is TaskStatus.done


# --------------------------------------------------------------------------
# Recovery for one name, after start (T083, 22 §Add step 3)
# --------------------------------------------------------------------------


class Sleeper:
    """A body that announces itself and parks until it is cancelled."""

    def __init__(self) -> None:
        self.started = asyncio.Event()

    def workflow(self, name: str) -> Workflow:
        wf = Workflow(name)

        @wf.node(start=True)
        async def only() -> str:
            self.started.set()
            await asyncio.sleep(3600)
            return "landed"  # pragma: no cover - cancelled first

        return wf


async def test_a_name_added_back_after_an_unregister_recovers_its_rows(
    start_engine, store: Store, wait_for
) -> None:
    """The round trip 22 §Remove and §Add describe, at the engine.

    ``unregister`` leaves the row ``in_progress``; ``register`` and
    ``recover(engine, [name])`` reset exactly that workflow's rows and
    announce them — while the sibling's row, held by a live attempt of
    this engine, is left alone.
    """

    doomed, sibling = Sleeper(), Sleeper()
    engine: Engine = await start_engine(
        (doomed.workflow("doomed"), Pool("test", 2)),
        (sibling.workflow("sibling"), Pool("test", 2)),
    )
    interrupted = await engine.ops.submit("doomed", "interrupted")
    held = await engine.ops.submit("sibling", "held")
    await wait_for(doomed.started)
    await wait_for(sibling.started)
    (interrupted_task,) = await tasks_of(store, interrupted.id)
    (held_task,) = await tasks_of(store, held.id)

    assert await engine.unregister("doomed") == [interrupted_task.id]
    assert await status_of(store, interrupted_task.id) is TaskStatus.in_progress

    engine.register(doomed.workflow("doomed").finalize(), Pool("test", 2))
    assert await recover(engine, ["doomed"]) == [interrupted_task.id]

    assert await status_of(store, interrupted_task.id) is TaskStatus.ready
    assert await token_hash_of(store, interrupted_task.id) is None
    assert await status_of(store, held_task.id) is TaskStatus.in_progress
    (event,) = await engine_events(store, EventName.engine_recovered)
    assert event.data == {"task_ids": [interrupted_task.id]}
    assert event.run_id is None


async def test_recovery_for_a_name_with_nothing_to_reset_announces_nothing(
    start_engine, store: Store
) -> None:
    engine: Engine = await start_engine(workflow("quiet"))
    await engine.ops.submit("quiet", "a run")

    assert await recover(engine, ["quiet"]) == []
    assert await engine_events(store, EventName.engine_recovered) == []


async def test_a_row_held_by_a_live_attempt_is_not_reset_under_it(
    start_engine, store: Store, wait_for
) -> None:
    """The one difference from boot: this process may already be running some.

    The name is bound before recovery is asked for (22 §Add's order), so
    a tick in between can have claimed a row of it; that row is held by
    an attempt of this engine and is excluded, while a row a dead process
    left is reset beside it.
    """

    sleeper = Sleeper()
    engine: Engine = await start_engine((sleeper.workflow("mixed"), Pool("test", 1)))
    live = await engine.ops.submit("mixed", "live")
    await wait_for(sleeper.started)
    (live_task,) = await tasks_of(store, live.id)
    dead = await submit(store, "mixed")
    await force(store, dead, status=TaskStatus.in_progress.value, token_hash="d" * 64)
    assert engine.attempts_of("mixed") == [live_task.id]

    assert await recover(engine, ["mixed"]) == [dead]

    assert await status_of(store, live_task.id) is TaskStatus.in_progress
    assert await status_of(store, dead) is TaskStatus.ready
    assert engine.scheduler.in_flight == (live_task.id,)
    (event,) = await engine_events(store, EventName.engine_recovered)
    assert event.data == {"task_ids": [dead]}


async def test_recovery_refuses_an_unregistered_name_and_writes_nothing(
    engines, store: Store
) -> None:
    engine: Engine = engines()
    engine.register(workflow("registered").finalize(), Pool("test", 1))
    orphan = await submit(store, "gone_away")
    await force(store, orphan, status=TaskStatus.in_progress.value)

    with pytest.raises(KeyError, match=r"unregistered workflows \['gone_away'\]"):
        await recover(engine, ["registered", "gone_away"])

    assert await status_of(store, orphan) is TaskStatus.in_progress
    assert await engine_events(store, EventName.engine_recovered) == []


async def tasks_of(store: Store, run_id: str) -> list[TaskRow]:
    async with store.reader() as reader:
        return await reader.tasks.list_for_run(run_id)

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
"""

from __future__ import annotations

from typing import Any

from athanore.engine import Engine
from athanore.engine.pools import Pool
from athanore.engine.recovery import recover
from athanore.events.names import EventName
from athanore.store.rows import EventRow, TaskStatus
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

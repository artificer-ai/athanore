"""The failure path: retries, timeouts, dead-letters, cancellation (T024a).

Rule 3 is "the exception is the failure policy", and 04 §Failure classes
refines it by *type*: a ``GraphError`` or a ``NonRetryable`` is a decision
the code has already made, so retrying it only burns inference, while
everything else — a flaky agent, a timeout — gets the node's remaining
attempts.

Two of these tests are load-bearing beyond the arithmetic:

- **a retry keeps ``created``.** It is the last tiebreaker of the
  dispatch order (04), so a retry that took a fresh timestamp would
  overtake everything enqueued while its first attempt ran, and a
  flapping node would starve the queue.
- **a cancelled attempt writes nothing at all.** An operator cancel has
  already recorded ``cancelled``, and a shutdown deliberately leaves the
  row ``in_progress`` for recovery to reset (D52). The assertion is that
  the row is *untouched*, not merely that nothing was raised: a status
  written here is how a graceful restart becomes lost work.
"""

from __future__ import annotations

import asyncio

import pytest

from athanore.engine.errors import NonRetryable
from athanore.events.names import EventName
from athanore.store.rows import LogAuthor, LogKind, RunStatus, TaskStatus
from athanore.workflow import Workflow

# --------------------------------------------------------------------------
# Workflows
# --------------------------------------------------------------------------


def failing(exc: BaseException, retries: int | None = None) -> Workflow:
    """One node, which raises ``exc`` every time it is attempted."""

    wf = Workflow("failing")

    @wf.node(start=True, retries=retries)
    async def only():
        raise exc

    return wf


def ambiguous() -> Workflow:
    """A node with two successors that returns a plain value: a GraphError."""

    wf = Workflow("ambiguous")

    @wf.node(start=True)
    async def choose(left, right):
        return {"not": "a ref"}

    @wf.node()
    async def left(*, deliverable): ...

    @wf.node()
    async def right(*, deliverable): ...

    return wf


# --------------------------------------------------------------------------
# Retry
# --------------------------------------------------------------------------


async def test_a_raising_body_is_retried_keeping_created_and_incrementing_attempt(
    harness,
) -> None:
    harness.register(failing(RuntimeError("boom")))
    run_id = await harness.submit("failing")

    claimed = await harness.attempt()

    first = await harness.task(claimed.task.id)
    assert first.status is TaskStatus.failed
    assert first.error == repr(RuntimeError("boom"))
    assert first.finished is not None

    first, retry = await harness.at(run_id, "only")
    assert retry.status is TaskStatus.ready
    assert retry.attempt == 2
    assert retry.created == first.created
    assert (retry.priority, retry.explicit) == (first.priority, first.explicit)
    assert retry.payload == first.payload
    assert retry.lineage == {"from": first.id, "reason": "retry"}
    assert (await harness.run(run_id)).status is RunStatus.running


async def test_the_failure_event_names_the_retry(harness) -> None:
    harness.register(failing(RuntimeError("boom")))
    run_id = await harness.submit("failing")

    await harness.attempt()

    _first, retry = await harness.at(run_id, "only")
    (failed,) = await harness.events_named(run_id, EventName.task_failed)
    assert failed.data == {
        "node": "only",
        "attempt": 1,
        "error": repr(RuntimeError("boom")),
        "retryable": True,
        "will_retry": True,
        "retry_task_id": retry.id,
    }
    (enqueued,) = await harness.events_named(run_id, EventName.task_enqueued)
    assert enqueued.data["reason"] == "retry"
    assert enqueued.data["attempt"] == 2


async def test_the_failure_is_written_to_the_work_log(harness) -> None:
    harness.register(failing(RuntimeError("boom")))
    run_id = await harness.submit("failing")

    await harness.attempt()

    (entry,) = await harness.log(run_id)
    assert entry.kind is LogKind.failure
    assert entry.author is LogAuthor.engine
    assert entry.text == "attempt 1 failed: boom"
    assert entry.node == "only"


async def test_the_third_failure_of_a_retries_3_node_dead_letters(harness) -> None:
    harness.register(failing(RuntimeError("boom"), retries=3))
    run_id = await harness.submit("failing")

    await harness.drain()

    attempts = await harness.at(run_id, "only")
    assert [task.attempt for task in attempts] == [1, 2, 3]
    assert [task.status for task in attempts] == [
        TaskStatus.failed,
        TaskStatus.failed,
        TaskStatus.dead_letter,
    ]
    assert (await harness.run(run_id)).status is RunStatus.failed


async def test_retries_0_dead_letters_on_the_first_attempt(harness) -> None:
    """``retries`` of ``None`` is the server default; ``0`` is none (D102)."""

    harness.register(failing(RuntimeError("boom"), retries=0))
    run_id = await harness.submit("failing")

    await harness.drain()

    (only,) = await harness.at(run_id, "only")
    assert only.status is TaskStatus.dead_letter


# --------------------------------------------------------------------------
# Dead-letter on the first attempt
# --------------------------------------------------------------------------


async def test_non_retryable_dead_letters_on_the_first_attempt_and_fails_the_run(
    harness,
) -> None:
    harness.register(failing(NonRetryable("refused")))
    run_id = await harness.submit("failing")

    claimed = await harness.attempt()

    (only,) = await harness.at(run_id, "only")
    assert only.id == claimed.task.id
    assert only.status is TaskStatus.dead_letter
    assert only.error == repr(NonRetryable("refused"))

    run = await harness.run(run_id)
    assert run.status is RunStatus.failed

    (failed,) = await harness.events_named(run_id, EventName.task_failed)
    assert failed.data["retryable"] is False
    assert failed.data["will_retry"] is False
    assert "retry_task_id" not in failed.data
    (dead,) = await harness.events_named(run_id, EventName.task_dead_lettered)
    assert dead.data == {
        "node": "only",
        "attempt": 1,
        "error": repr(NonRetryable("refused")),
    }
    (run_failed,) = await harness.events_named(run_id, EventName.run_failed)
    assert run_failed.data["node"] == "only"
    assert run_failed.data["task_id"] == only.id
    assert "code" not in run_failed.data


async def test_a_graph_error_dead_letters_on_the_first_attempt(harness) -> None:
    harness.register(ambiguous())
    run_id = await harness.submit("ambiguous")

    await harness.attempt()

    (choose,) = await harness.at(run_id, "choose")
    assert choose.status is TaskStatus.dead_letter
    assert "successors" in (choose.error or "")
    assert await harness.at(run_id, "left") == []
    assert (await harness.run(run_id)).status is RunStatus.failed


async def test_a_node_the_workflow_no_longer_declares_dead_letters(harness) -> None:
    """A node renamed while a run was queued is a defect, not a retry."""

    harness.register(failing(RuntimeError("unused")))
    run_id = await harness.submit("failing")
    async with harness.store.uow() as uow:
        await uow.tasks.enqueue(run_id, "vanished", None, 0, False)

    # Newest first (04 §Dispatch order), so this claims the stranded task.
    claimed = await harness.attempt()
    assert claimed.task.node == "vanished"

    (vanished,) = await harness.at(run_id, "vanished")
    assert vanished.status is TaskStatus.dead_letter
    assert "no node 'vanished'" in (vanished.error or "")


# --------------------------------------------------------------------------
# Timeouts
# --------------------------------------------------------------------------


async def test_a_node_timeout_fails_the_attempt_and_is_retried(harness) -> None:
    wf = Workflow("slow")

    @wf.node(start=True, timeout=0.05)
    async def only():
        await asyncio.sleep(5)

    harness.register(wf)
    run_id = await harness.submit("slow")

    await harness.attempt()

    first, retry = await harness.at(run_id, "only")
    assert first.status is TaskStatus.failed
    assert first.error == repr(TimeoutError())
    assert retry.attempt == 2
    assert retry.status is TaskStatus.ready


async def test_a_body_inside_its_timeout_is_not_disturbed(harness) -> None:
    wf = Workflow("brisk")

    @wf.node(start=True, timeout=5)
    async def only():
        await asyncio.sleep(0.01)
        return []

    harness.register(wf)
    run_id = await harness.submit("brisk")

    await harness.attempt()

    (task,) = await harness.at(run_id, "only")
    assert task.status is TaskStatus.done
    assert (await harness.run(run_id)).status is RunStatus.completed


# --------------------------------------------------------------------------
# Cancellation
# --------------------------------------------------------------------------


async def test_cancelling_an_attempt_leaves_the_row_in_progress_and_records_nothing(
    harness,
) -> None:
    running = asyncio.Event()
    wf = Workflow("parked")

    @wf.node(start=True)
    async def only():
        running.set()
        await asyncio.sleep(30)

    harness.register(wf)
    run_id = await harness.submit("parked")

    (claimed,) = await harness.claim()
    attempt = harness.spawn(claimed)
    await asyncio.wait_for(running.wait(), timeout=2)
    attempt.cancel()
    with pytest.raises(asyncio.CancelledError):
        await attempt

    (task,) = await harness.at(run_id, "only")
    assert task.status is TaskStatus.in_progress
    assert task.finished is None
    assert task.error is None
    assert task.result is None
    assert (await harness.run(run_id)).status is RunStatus.running
    assert await harness.event_names(run_id) == [
        EventName.task_started,
        EventName.run_started,
    ]
    assert await harness.log(run_id) == []
    # The slot still came back, and the registry is empty again.
    assert harness.pool.leased == 0
    assert len(harness.engine.live) == 0
    assert harness.engine.notifications == 1

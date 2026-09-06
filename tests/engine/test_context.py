"""Tests for :mod:`athanore.engine.context` and :mod:`athanore.engine.services`.

Two things are worth asserting here and nothing else is close in weight.

The **binding** is how every user-land helper finds its attempt, so it has
to be exact in both directions: absent outside a body, and restored to the
outer attempt when an inner one ends. A fan-out that came back with the
wrong context bound would write another run's log entries.

The **namespace restriction** on ``services.events.publish`` is the
security-shaped one. Everything but ``plugin.*`` describes state the engine
owns and is emitted inside the transaction that changed it (03 invariant
7), so a body able to publish ``task.done`` could tell every SSE client and
plugin subscriber that a task it is still running has finished.
"""

from __future__ import annotations

import pytest

from athanore.engine.context import (
    TaskContext,
    bind,
    current_task,
    maybe_current_task,
)
from athanore.engine.services import TaskServices
from athanore.events.bus import EventBus
from athanore.events.names import EventName
from athanore.store.rows import LogAuthor, LogKind
from athanore.store.uow import Store

WORKFLOW = "demo"
FLUSH_INTERVAL = 0.05


async def make_task(store: Store, node: str = "build") -> tuple[str, int]:
    """A run with one task on it, as the runner would have claimed."""

    async with store.uow() as uow:
        run = await uow.runs.insert(WORKFLOW, "a run")
        task = await uow.tasks.enqueue(run.id, node, None, priority=0, explicit=False)
    return run.id, task.id


def make_context(
    store: Store, run_id: str, task_id: int, node: str = "build"
) -> TaskContext:
    services = TaskServices(
        store,
        run_id=run_id,
        task_id=task_id,
        node=node,
        workflow=WORKFLOW,
        flush_interval=FLUSH_INTERVAL,
    )
    return TaskContext(
        run_id=run_id,
        task_id=task_id,
        workflow=WORKFLOW,
        node=node,
        attempt=1,
        token="tok-" + str(task_id),
        api_base="http://127.0.0.1:4002",
        services=services,
    )


# --------------------------------------------------------------------------
# The binding
# --------------------------------------------------------------------------


def test_current_task_raises_outside_a_binding() -> None:
    assert maybe_current_task() is None
    with pytest.raises(RuntimeError, match="no task context"):
        current_task()


async def test_bind_makes_the_context_current_and_unbinds_after(store: Store) -> None:
    run_id, task_id = await make_task(store)
    ctx = make_context(store, run_id, task_id)

    with bind(ctx) as bound:
        assert bound is ctx
        assert current_task() is ctx
        assert maybe_current_task() is ctx

    assert maybe_current_task() is None


async def test_nested_binds_restore_the_outer_context(store: Store) -> None:
    """A body that enters another attempt's context keeps its own."""

    run_id, outer_id = await make_task(store, node="outer")
    async with store.uow() as uow:
        inner_task = await uow.tasks.enqueue(
            run_id, "inner", None, priority=0, explicit=False
        )
    outer = make_context(store, run_id, outer_id, node="outer")
    inner = make_context(store, run_id, inner_task.id, node="inner")

    with bind(outer):
        with bind(inner):
            assert current_task() is inner
        assert current_task() is outer
    assert maybe_current_task() is None


async def test_the_outer_context_is_restored_even_when_the_inner_raises(
    store: Store,
) -> None:
    run_id, task_id = await make_task(store)
    outer = make_context(store, run_id, task_id)
    inner = make_context(store, run_id, task_id, node="inner")

    with bind(outer):
        with pytest.raises(ZeroDivisionError):
            with bind(inner):
                raise ZeroDivisionError
        assert current_task() is outer


async def test_the_private_engine_fields_start_empty(store: Store) -> None:
    """T026 sets both; nothing else may assume they are populated."""

    run_id, task_id = await make_task(store)
    ctx = make_context(store, run_id, task_id)

    assert ctx._timeout is None
    assert ctx._released_at is None
    assert ctx.request_ordinal == 0
    assert ctx.output_model is None
    assert ctx.ask_policy == "off"
    assert ctx.last_rejection is None


# --------------------------------------------------------------------------
# The log service
# --------------------------------------------------------------------------


async def test_log_append_writes_a_row_and_emits_log_appended(
    store: Store, bus: EventBus
) -> None:
    run_id, task_id = await make_task(store)
    ctx = make_context(store, run_id, task_id)
    subscription = bus.subscribe(["log.appended"])

    entry = await ctx.services.log.append("shipped it", kind=LogKind.deliverable)

    async with store.reader() as reader:
        rows = await reader.log.list(run_id)
    assert [row.id for row in rows] == [entry.id]
    assert rows[0].task_id == task_id
    assert rows[0].node == "build"
    assert rows[0].author is LogAuthor.agent
    assert rows[0].kind is LogKind.deliverable
    assert rows[0].text == "shipped it"

    event = subscription.queue.get_nowait()
    assert event.name == EventName.log_appended
    assert event.run_id == run_id
    assert event.task_id == task_id
    assert event.data == {
        "log_id": entry.id,
        "author": "agent",
        "node": "build",
        "kind": "deliverable",
        "preview": "shipped it",
    }
    assert event.id is not None
    subscription.close()


async def test_log_append_previews_the_first_200_characters(
    store: Store, bus: EventBus
) -> None:
    """An event never carries full log text (18 §Rules)."""

    run_id, task_id = await make_task(store)
    ctx = make_context(store, run_id, task_id)
    subscription = bus.subscribe(["log.appended"])

    text = "x" * 500
    await ctx.services.log.append(text, author=LogAuthor.engine)

    event = subscription.queue.get_nowait()
    assert event.data["preview"] == "x" * 200
    assert "kind" not in event.data
    assert event.data["author"] == "engine"
    subscription.close()


async def test_log_append_refuses_an_author_outside_the_vocabulary(
    store: Store,
) -> None:
    run_id, task_id = await make_task(store)
    ctx = make_context(store, run_id, task_id)

    with pytest.raises(ValueError):
        await ctx.services.log.append("who wrote this", author="nobody")

    async with store.reader() as reader:
        assert await reader.log.list(run_id) == []


# --------------------------------------------------------------------------
# The submission service
# --------------------------------------------------------------------------


async def test_accept_stores_the_payload_and_latest_returns_it(
    store: Store, bus: EventBus
) -> None:
    run_id, task_id = await make_task(store)
    ctx = make_context(store, run_id, task_id)
    subscription = bus.subscribe(["submission.accepted"])

    assert await ctx.services.submissions.latest() is None
    first = await ctx.services.submissions.accept({"answer": 1})
    second = await ctx.services.submissions.accept({"answer": 2})

    latest = await ctx.services.submissions.latest()
    assert latest is not None
    assert latest.id == second.id
    assert latest.payload == {"answer": 2}

    names = [subscription.queue.get_nowait().data for _ in range(2)]
    assert names == [
        {"node": "build", "submission_id": first.id},
        {"node": "build", "submission_id": second.id},
    ]
    subscription.close()


async def test_reject_emits_an_event_and_stores_no_row(
    store: Store, bus: EventBus
) -> None:
    run_id, task_id = await make_task(store)
    ctx = make_context(store, run_id, task_id)
    subscription = bus.subscribe(["submission.rejected"])

    rejection = await ctx.services.submissions.reject(
        [
            {
                "loc": ("answer",),
                "msg": "Input should be a valid integer",
                "type": "int_parsing",
                "input": "not a number",
                "url": "https://errors.pydantic.dev/",
            }
        ],
        {"type": "object", "properties": {"answer": {"type": "integer"}}},
    )

    assert await ctx.services.submissions.latest() is None
    event = subscription.queue.get_nowait()
    assert event.name == EventName.submission_rejected
    assert event.data == {
        "node": "build",
        "errors": [
            {
                "loc": ["answer"],
                "msg": "Input should be a valid integer",
                "type": "int_parsing",
            }
        ],
    }
    # What the endpoint answers 422 with and records as `ctx.last_rejection`.
    assert rejection["errors"] == event.data["errors"]
    assert rejection["schema"]["properties"] == {"answer": {"type": "integer"}}
    subscription.close()


async def test_reject_refuses_an_error_missing_18s_fields(store: Store) -> None:
    run_id, task_id = await make_task(store)
    ctx = make_context(store, run_id, task_id)

    with pytest.raises(ValueError, match="msg, type"):
        await ctx.services.submissions.reject([{"loc": ["answer"]}], {})


# --------------------------------------------------------------------------
# The run service and the unwired members
# --------------------------------------------------------------------------


async def test_run_get_returns_the_run(store: Store) -> None:
    run_id, task_id = await make_task(store)
    ctx = make_context(store, run_id, task_id)

    run = await ctx.services.run.get()
    assert run.id == run_id
    assert run.workflow == WORKFLOW
    assert run.title == "a run"


async def test_lease_released_raises_until_t026(store: Store) -> None:
    """A no-op would hold the slot through the wait; it must not pretend."""

    run_id, task_id = await make_task(store)
    ctx = make_context(store, run_id, task_id)

    with pytest.raises(NotImplementedError, match="T026"):
        ctx.services.lease.released()


async def test_the_requests_port_raises_until_t032(store: Store) -> None:
    run_id, task_id = await make_task(store)
    ctx = make_context(store, run_id, task_id)

    with pytest.raises(NotImplementedError, match="T032"):
        await ctx.services.requests.wait(1)


async def test_a_wired_requests_port_is_used_as_given(store: Store) -> None:
    """The port is injected, so T032 replaces the unwired one and nothing else."""

    run_id, task_id = await make_task(store)
    port = object()
    services = TaskServices(
        store,
        run_id=run_id,
        task_id=task_id,
        node="build",
        workflow=WORKFLOW,
        flush_interval=FLUSH_INTERVAL,
        requests=port,  # type: ignore[arg-type]
    )
    assert services.requests is port


# --------------------------------------------------------------------------
# The event port
# --------------------------------------------------------------------------


async def test_publish_writes_and_publishes_a_plugin_event(
    store: Store, bus: EventBus
) -> None:
    run_id, task_id = await make_task(store)
    ctx = make_context(store, run_id, task_id)
    subscription = bus.subscribe(["plugin.*.*"])

    event = await ctx.services.events.publish(
        f"plugin.{WORKFLOW}.built", {"artifact": "app.zip"}
    )

    assert event.id is not None
    delivered = subscription.queue.get_nowait()
    assert delivered.name == f"plugin.{WORKFLOW}.built"
    assert delivered.data == {"artifact": "app.zip"}
    assert delivered.run_id == run_id
    assert delivered.task_id == task_id

    async with store.reader() as reader:
        stored = await reader.events.list_for_run(run_id)
    assert [row.name for row in stored] == [f"plugin.{WORKFLOW}.built"]
    subscription.close()


@pytest.mark.parametrize(
    "name",
    [
        "task.done",
        "run.completed",
        "task.stream",
        "engine.stopping",
        "pluginish.demo.x",
    ],
)
async def test_publish_refuses_the_engines_vocabulary(store: Store, name: str) -> None:
    """The security-shaped one: user land cannot forge `task.done`."""

    run_id, task_id = await make_task(store)
    ctx = make_context(store, run_id, task_id)

    with pytest.raises(ValueError) as raised:
        await ctx.services.events.publish(name, {})

    message = str(raised.value)
    assert name in message
    assert "restricted to plugin." in message

    async with store.reader() as reader:
        assert await reader.events.list_for_run(run_id) == []


@pytest.mark.parametrize("name", ["plugin.demo", "plugin.demo.a.b", "plugin.demo.1st"])
async def test_publish_refuses_a_malformed_plugin_name(store: Store, name: str) -> None:
    run_id, task_id = await make_task(store)
    ctx = make_context(store, run_id, task_id)

    with pytest.raises(ValueError, match="not a plugin event"):
        await ctx.services.events.publish(name, {})


async def test_publish_refuses_another_workflows_namespace(store: Store) -> None:
    """18 §Plugins: a workflow publishes only in its own namespace."""

    run_id, task_id = await make_task(store)
    ctx = make_context(store, run_id, task_id)

    with pytest.raises(ValueError, match="publishes only in its own"):
        await ctx.services.events.publish("plugin.other.built", {})


async def test_publish_refuses_data_that_is_not_an_object(store: Store) -> None:
    run_id, task_id = await make_task(store)
    ctx = make_context(store, run_id, task_id)

    with pytest.raises(TypeError, match="must be a JSON object"):
        await ctx.services.events.publish(
            f"plugin.{WORKFLOW}.built",
            ["not", "an", "object"],  # type: ignore[arg-type]
        )

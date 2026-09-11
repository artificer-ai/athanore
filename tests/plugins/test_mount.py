"""Mounted routes, the context dependency, and `on` dispatch (T049a, 09).

Driven through a real `create_app()` over ASGI, because what is under
test is the whole of the path a plugin route takes: the operator door,
the query parameters FastAPI derives from the `PluginContext`
annotation, the 404 that keeps one workflow out of another's runs, and
the error shape a `PluginError` comes back as.

The dispatch tests run a real engine to completion. That is the only way
to assert the property that matters — a handler that raises does not
affect the engine — because "the run still completed" is a claim about
the engine, not about the dispatcher.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from athanore.engine import Engine
from athanore.events.bus import EventBus
from athanore.events.model import Event
from athanore.plugins.context import NO_RUN, NO_TASK, PluginContext, PluginHost
from athanore.plugins.decl import Handler, PluginError
from athanore.plugins.mount import _builtins_first, _in_scope, dispatch_handlers
from athanore.plugins.registry import BUILTIN_WORKFLOW, PluginSpec, collect, validate
from athanore.store.uow import Store
from athanore.workflow import Workflow


def gamedev() -> Workflow:
    """A one-node workflow with a route, an action and two panels."""

    wf = Workflow("gamedev")

    @wf.node(start=True)
    async def play():
        """Play one round."""
        return {"word": "athanor"}

    @wf.route("/words")
    async def words(ctx: PluginContext, limit: int = 50) -> dict:
        """Every word this run has used."""
        return {
            "workflow": ctx.workflow,
            "run_id": ctx.run_id,
            "task_id": ctx.task_id,
            "node": ctx.node,
            "title": ctx.run.title if ctx.run is not None else None,
            "task_node": ctx.task.node if ctx.task is not None else None,
            "limit": limit,
        }

    @wf.route("/log")
    async def log(ctx: PluginContext) -> dict:
        """Append to the run's work log, which needs a run and a task."""
        entry = await ctx.services.log.append("from a plugin", author="user")
        return {"id": entry.id}

    @wf.route("/everything")
    async def everything(ctx: PluginContext) -> dict:
        """A global route: no run in scope, and none needed."""
        runs = await ctx.services.run.list()
        return {"run": ctx.run_id, "runs": [run.id for run in runs]}

    @wf.route("/needs-a-run")
    async def needs_a_run(ctx: PluginContext) -> dict:
        """Reach for a run-scoped service from wherever this was called."""
        return {"log": repr(ctx.services.log)}

    wf.panel(
        "Words", slot="run", kind="table", source=words, refresh_on=["log.appended"]
    )
    return wf


def other() -> Workflow:
    """A second workflow, so ownership has something to be wrong about."""

    wf = Workflow("other")

    @wf.node(start=True)
    async def only():
        return None

    @wf.route("/peek")
    async def peek(ctx: PluginContext) -> dict:
        return {"run_id": ctx.run_id}

    return wf


async def submit(client: httpx.AsyncClient, workflow: str = "gamedev") -> str:
    """Queue a run through the API, and return its id."""

    response = await client.post(
        f"/api/workflows/{workflow}/runs", json={"title": "a run"}
    )
    assert response.status_code == 201, response.text
    return response.json()["run_id"]


async def first_task(store: Store, run_id: str) -> int:
    """The id of the run's start task."""

    async with store.reader() as reader:
        tasks = await reader.tasks.list_for_run(run_id)
    assert tasks, "the run has no tasks"
    return tasks[0].id


# -- routes and the context dependency --------------------------------------


async def test_a_route_resolves_its_context(
    app_with: Callable[..., Awaitable[httpx.AsyncClient]], store: Store
):
    client = await app_with(gamedev())
    run_id = await submit(client)
    task_id = await first_task(store, run_id)

    response = await client.get(
        "/api/plugins/gamedev/words", params={"run_id": run_id, "task_id": task_id}
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "workflow": "gamedev",
        "run_id": run_id,
        "task_id": task_id,
        "node": "play",
        "title": "a run",
        "task_node": "play",
        "limit": 50,
    }


async def test_a_routes_own_parameters_are_ordinary_fastapi_ones(
    app_with: Callable[..., Awaitable[httpx.AsyncClient]],
):
    client = await app_with(gamedev())
    run_id = await submit(client)

    response = await client.get(
        "/api/plugins/gamedev/words", params={"run_id": run_id, "limit": 3}
    )

    assert response.json()["limit"] == 3
    assert response.json()["task_id"] is None

    bad = await client.get(
        "/api/plugins/gamedev/words", params={"run_id": run_id, "limit": "many"}
    )
    assert bad.status_code == 422
    assert bad.json()["code"] == "validation"


async def test_a_foreign_run_id_is_404(
    app_with: Callable[..., Awaitable[httpx.AsyncClient]],
):
    client = await app_with(gamedev(), other())
    run_id = await submit(client, "other")

    response = await client.get("/api/plugins/gamedev/words", params={"run_id": run_id})

    assert response.status_code == 404
    assert response.json()["code"] == "plugin_error"
    assert "belongs to workflow 'other'" in response.json()["error"]


async def test_a_run_that_does_not_exist_is_404(
    app_with: Callable[..., Awaitable[httpx.AsyncClient]],
):
    client = await app_with(gamedev())

    response = await client.get(
        "/api/plugins/gamedev/words", params={"run_id": "01JQNOTAREALRUNID0000000"}
    )

    assert response.status_code == 404
    assert response.json()["code"] == "plugin_error"


async def test_a_task_of_another_run_is_404(
    app_with: Callable[..., Awaitable[httpx.AsyncClient]], store: Store
):
    client = await app_with(gamedev())
    first = await submit(client)
    second = await submit(client)

    response = await client.get(
        "/api/plugins/gamedev/words",
        params={"run_id": first, "task_id": await first_task(store, second)},
    )

    assert response.status_code == 404
    assert "does not belong to run" in response.json()["error"]


async def test_a_node_the_workflow_does_not_have_is_404(
    app_with: Callable[..., Awaitable[httpx.AsyncClient]],
):
    client = await app_with(gamedev())
    run_id = await submit(client)

    response = await client.get(
        "/api/plugins/gamedev/words", params={"run_id": run_id, "node": "nope"}
    )

    assert response.status_code == 404
    assert "has no node 'nope'" in response.json()["error"]


async def test_a_global_route_has_no_run_and_a_run_scoped_service_raises(
    app_with: Callable[..., Awaitable[httpx.AsyncClient]],
):
    """09 §Context and scopes, both halves of it."""

    client = await app_with(gamedev())
    run_id = await submit(client)

    everything = await client.get("/api/plugins/gamedev/everything")
    assert everything.status_code == 200
    assert everything.json() == {"run": None, "runs": [run_id]}

    refused = await client.get("/api/plugins/gamedev/needs-a-run")
    assert refused.status_code == 400
    assert refused.json() == {"error": NO_RUN, "code": "plugin_error"}


async def test_a_run_scope_without_a_task_refuses_the_work_log(
    app_with: Callable[..., Awaitable[httpx.AsyncClient]],
):
    client = await app_with(gamedev())
    run_id = await submit(client)

    response = await client.get("/api/plugins/gamedev/log", params={"run_id": run_id})

    assert response.status_code == 400
    assert response.json() == {"error": NO_TASK, "code": "plugin_error"}


async def test_a_task_scope_writes_the_work_log(
    app_with: Callable[..., Awaitable[httpx.AsyncClient]], store: Store
):
    client = await app_with(gamedev())
    run_id = await submit(client)
    task_id = await first_task(store, run_id)

    response = await client.get("/api/plugins/gamedev/log", params={"task_id": task_id})

    assert response.status_code == 200
    async with store.reader() as reader:
        entries = await reader.log.list(run_id)
    assert [(entry.text, entry.author, entry.node) for entry in entries] == [
        ("from a plugin", "user", "play")
    ]


async def test_a_global_route_lists_only_its_own_workflows_runs(
    app_with: Callable[..., Awaitable[httpx.AsyncClient]],
):
    """12 §Plugins: a plugin cannot reach another workflow's runs."""

    client = await app_with(gamedev(), other())
    mine = await submit(client, "gamedev")
    await submit(client, "other")

    response = await client.get("/api/plugins/gamedev/everything")

    assert response.json()["runs"] == [mine]


async def test_plugin_routes_are_operator_routes(
    app_with: Callable[..., Awaitable[httpx.AsyncClient]],
):
    """They hang on the same door, and say so in the document."""

    client = await app_with(gamedev())
    document = (await client.get("/openapi.json")).json()

    for path in ("/api/plugins", "/api/plugins/gamedev/words"):
        operation = document["paths"][path]["get"]
        assert operation["security"] == [{"operatorBearer": []}]
        assert "401" in operation["responses"]
        assert operation["tags"] == ["plugins"]


async def test_the_context_parameters_are_documented(
    app_with: Callable[..., Awaitable[httpx.AsyncClient]],
):
    client = await app_with(gamedev())
    document = (await client.get("/openapi.json")).json()

    operation = document["paths"]["/api/plugins/gamedev/words"]["get"]
    assert {parameter["name"] for parameter in operation["parameters"]} == {
        "run_id",
        "task_id",
        "node",
        "limit",
    }


# -- the manifest -----------------------------------------------------------


async def test_the_manifest_endpoint(
    app_with: Callable[..., Awaitable[httpx.AsyncClient]],
):
    client = await app_with(gamedev())

    response = await client.get("/api/plugins")

    assert response.status_code == 200
    assert response.json() == [
        {
            "workflow": "gamedev",
            "panels": [
                {
                    "name": "Words",
                    "slot": "run",
                    "placement": "pane",
                    "kind": "table",
                    "scope": "run",
                    "source": "/api/plugins/gamedev/words",
                    "refresh_on": ["log.appended"],
                }
            ],
            "actions": [],
            "assets": [],
        }
    ]


async def test_the_manifest_of_a_server_with_no_plugins_is_empty(
    app_with: Callable[..., Awaitable[httpx.AsyncClient]],
):
    client = await app_with()

    assert (await client.get("/api/plugins")).json() == []


async def test_the_manifest_lists_builtins_first(
    app_with: Callable[..., Awaitable[httpx.AsyncClient]],
):
    """09 §Builtins are plugins: the core's own views come first."""

    async def noted(ctx: PluginContext, event: Event) -> None:
        return None

    # A spec that declares something: one that declares nothing is held
    # nowhere and has no entry (09 §Wire contract, `MountedPlugins`).
    builtin = PluginSpec(
        workflow=BUILTIN_WORKFLOW, handlers=(Handler(event="run.created", fn=noted),)
    )
    client = await app_with(gamedev(), extra=[builtin])

    assert [
        entry["workflow"] for entry in (await client.get("/api/plugins")).json()
    ] == [
        BUILTIN_WORKFLOW,
        "gamedev",
    ]


def test_builtins_first_keeps_the_rest_in_registration_order():
    specs = [
        PluginSpec(workflow="b"),
        PluginSpec(workflow=BUILTIN_WORKFLOW),
        PluginSpec(workflow="a"),
    ]

    assert [spec.workflow for spec in _builtins_first(specs)] == [
        BUILTIN_WORKFLOW,
        "b",
        "a",
    ]


async def test_a_workflow_carries_its_own_declarations(
    app_with: Callable[..., Awaitable[httpx.AsyncClient]],
):
    """08 §Workflows: `plugin: {panels, actions}` on the workflow itself."""

    client = await app_with(gamedev(), other())

    body = {
        entry["name"]: entry for entry in (await client.get("/api/workflows")).json()
    }

    assert [panel["name"] for panel in body["gamedev"]["plugin"]["panels"]] == ["Words"]
    assert body["other"]["plugin"] == {"panels": [], "actions": []}


# -- `on` dispatch ----------------------------------------------------------


def recording(fired: list[str], *, raising: bool = False) -> Workflow:
    """A workflow whose run completes, with handlers on `run.completed`."""

    wf = Workflow("gamedev")

    @wf.node(start=True)
    async def play():
        return {"word": "athanor"}

    if raising:

        @wf.on("run.completed")
        async def explode(ctx: PluginContext, event: Event) -> None:
            fired.append("explode")
            raise RuntimeError("the plugin is broken")

    @wf.on("run.completed")
    async def done(ctx: PluginContext, event: Event) -> None:
        fired.append(
            f"{event.name}:{event.run_id}:{ctx.run.title if ctx.run else None}"
        )

    return wf


async def test_an_on_handler_receives_run_completed(
    app_with: Callable[..., Awaitable[httpx.AsyncClient]],
    run_to_completion: Callable[[str], Awaitable[Any]],
    wait_until: Callable[[Callable[[], bool]], Awaitable[None]],
):
    fired: list[str] = []
    client = await app_with(recording(fired), start=True)
    run_id = await submit(client)

    assert (await run_to_completion(run_id)).status == "completed"
    await wait_until(lambda: bool(fired))

    assert fired == [f"run.completed:{run_id}:a run"]


async def test_a_raising_handler_does_not_affect_the_engine(
    app_with: Callable[..., Awaitable[httpx.AsyncClient]],
    run_to_completion: Callable[[str], Awaitable[Any]],
    wait_until: Callable[[Callable[[], bool]], Awaitable[None]],
):
    """09 §Wire contract: logged and dropped, and the rest still run."""

    fired: list[str] = []
    client = await app_with(recording(fired, raising=True), start=True)
    run_id = await submit(client)

    run = await run_to_completion(run_id)
    await wait_until(lambda: len(fired) == 2)

    assert run.status == "completed"
    assert run.output == {"word": "athanor"}
    assert fired[0] == "explode"
    assert fired[1] == f"run.completed:{run_id}:a run"


async def test_a_handler_of_another_workflow_is_not_called(
    app_with: Callable[..., Awaitable[httpx.AsyncClient]],
    run_to_completion: Callable[[str], Awaitable[Any]],
    wait_until: Callable[[Callable[[], bool]], Awaitable[None]],
):
    fired: list[str] = []
    client = await app_with(recording(fired), other(), start=True)
    mine = await submit(client, "gamedev")
    theirs = await submit(client, "other")

    await run_to_completion(theirs)
    await run_to_completion(mine)
    await wait_until(lambda: bool(fired))
    # Long enough for a second delivery to have happened if it were going to.
    await asyncio.sleep(0.05)

    assert fired == [f"run.completed:{mine}:a run"]


def watching_deletes(fired: list[str], name: str) -> Workflow:
    """A workflow that watches runs of its own being deleted."""

    wf = Workflow(name)

    @wf.node(start=True)
    async def only():
        return None

    @wf.on("run.deleted")
    async def gone(ctx: PluginContext, event: Event) -> None:
        fired.append(
            f"{name}:{event.run_id}:{event.data.get('workflow')}:{ctx.run is None}"
        )

    return wf


async def test_run_deleted_reaches_only_the_workflow_that_owned_the_run(
    app_with: Callable[..., Awaitable[httpx.AsyncClient]],
    run_to_completion: Callable[[str], Awaitable[Any]],
    wait_until: Callable[[Callable[[], bool]], Awaitable[None]],
):
    """The row is gone by then, so the payload is what ownership is read from.

    Delivering it to every subscriber instead would hand `other` the run
    id, workflow and title of a `gamedev` run — the reach 12 §Plugins
    forbids and 09's "scope follows ownership" rules out.
    """

    fired: list[str] = []
    client = await app_with(
        watching_deletes(fired, "gamedev"), watching_deletes(fired, "other"), start=True
    )
    run_id = await submit(client, "gamedev")
    await run_to_completion(run_id)

    response = await client.delete(f"/api/runs/{run_id}")
    assert response.status_code == 204, response.text

    await wait_until(lambda: bool(fired))
    # Long enough for a second delivery to have happened if it were going to.
    await asyncio.sleep(0.05)

    # The owner's handler, with no run in scope, and nobody else's.
    assert fired == [f"gamedev:{run_id}:gamedev:True"]


def test_an_event_whose_owner_cannot_be_established_reaches_only_builtins():
    """Neither the store nor the payload knows: only `_builtin` owns every run."""

    about_a_run = Event(
        name="run.deleted", run_id="01J", data={}, created=datetime.now(UTC)
    )
    about_the_server = Event(
        name="engine.started", data={"pools": []}, created=datetime.now(UTC)
    )

    assert not _in_scope("gamedev", None, about_a_run)
    assert _in_scope(BUILTIN_WORKFLOW, None, about_a_run)
    assert _in_scope("gamedev", "gamedev", about_a_run)
    assert not _in_scope("gamedev", "other", about_a_run)
    # An `engine.*` event is about the server, not about anyone's run.
    assert _in_scope("gamedev", None, about_the_server)


class FlakyHost(PluginHost):
    """A host whose owner lookup fails the first time it is asked."""

    def __init__(self, store: Store) -> None:
        super().__init__(store)
        self.failures = 0

    async def workflow_of(self, run_id: str) -> str | None:
        if self.failures == 0:
            self.failures += 1
            raise RuntimeError("the database went away")
        return await super().workflow_of(run_id)


async def test_a_failing_owner_lookup_does_not_stop_the_dispatcher(
    store: Store,
    bus: EventBus,
    wait_until: Callable[[Callable[[], bool]], Awaitable[None]],
):
    """Log and continue, one level out from the handler.

    A store error in the lookup — or in the flush a context closes with —
    used to end the consumer task, and with it every `on` handler in the
    process, silently and for good.
    """

    fired: list[str] = []
    wf = Workflow("gamedev")

    @wf.node(start=True)
    async def only():
        return None

    @wf.on("run.created")
    async def created(ctx: PluginContext, event: Event) -> None:
        fired.append(event.name)

    @wf.on("run.deleted")
    async def deleted(ctx: PluginContext, event: Event) -> None:
        fired.append(event.name)

    graph = wf.finalize()
    spec = collect(wf)
    validate(spec, graph)
    host = FlakyHost(store)
    dispatch = dispatch_handlers(bus, [spec], host)
    try:
        bus.publish(
            Event(
                name="run.created",
                run_id="01J",
                data={"workflow": "gamedev", "title": "a run"},
                created=datetime.now(UTC),
            )
        )
        bus.publish(
            Event(
                name="run.deleted",
                run_id="01K",
                data={"workflow": "gamedev", "title": "a run"},
                created=datetime.now(UTC),
            )
        )
        await wait_until(lambda: bool(fired))
        await asyncio.sleep(0.05)
    finally:
        await dispatch.aclose()

    # The first event was lost with the lookup that raised; the second
    # was delivered, which is the whole claim.
    assert fired == ["run.deleted"]
    assert host.failures == 1


class UnflushableHost(PluginHost):
    """A host whose contexts raise on the way out.

    What a transcript's final flush is when the store has gone away: a
    write, made after the handlers have already run.
    """

    async def context(self, **kwargs: Any) -> PluginContext:
        context = await super().context(**kwargs)

        async def boom() -> None:
            raise RuntimeError("the transcript flush failed")

        context.aclose = boom  # pyright: ignore[reportAttributeAccessIssue]
        return context


async def test_a_context_that_will_not_close_does_not_skip_the_next_plugin(
    store: Store,
    bus: EventBus,
    wait_until: Callable[[Callable[[], bool]], Awaitable[None]],
):
    """The cleanup of one spec is not the delivery of the ones after it.

    A workflow's spec and a builtin one both see the same event — the
    builtin scope owns every run — so a failure closing the first
    context is exactly what would cost the second its handler.
    """

    fired: list[str] = []
    wf = Workflow("gamedev")

    @wf.node(start=True)
    async def only():
        return None

    @wf.on("run.created")
    async def mine(ctx: PluginContext, event: Event) -> None:
        fired.append("gamedev")

    spec = collect(wf)
    validate(spec, wf.finalize())

    async def theirs(ctx: PluginContext, event: Event) -> None:
        fired.append(BUILTIN_WORKFLOW)

    builtin = PluginSpec(
        workflow=BUILTIN_WORKFLOW,
        handlers=(Handler(event="run.created", fn=theirs),),
    )
    dispatch = dispatch_handlers(bus, [spec, builtin], UnflushableHost(store))
    try:
        bus.publish(
            Event(
                name="run.created",
                run_id="01J",
                data={"workflow": "gamedev", "title": "a run"},
                created=datetime.now(UTC),
            )
        )
        await wait_until(lambda: len(fired) == 2)
    finally:
        await dispatch.aclose()

    assert fired == ["gamedev", BUILTIN_WORKFLOW]


def _created(run_id: str, workflow: str = "gamedev") -> Event:
    """A ``run.created`` whose owner is on the payload (18 §Payloads)."""

    return Event(
        name="run.created",
        run_id=run_id,
        data={"workflow": workflow, "title": "a run"},
        created=datetime.now(UTC),
    )


def _subscriber(name: str, fired: list[str]) -> PluginSpec:
    """A ``gamedev`` spec with one ``run.created`` handler that records ``name``."""

    async def created(ctx: PluginContext, event: Event) -> None:
        fired.append(f"{name}:{event.run_id}")

    return PluginSpec(
        workflow="gamedev", handlers=(Handler(event="run.created", fn=created),)
    )


async def test_set_swaps_a_workflows_handlers_under_the_one_subscription(
    store: Store,
    bus: EventBus,
    wait_until: Callable[[Callable[[], bool]], Awaitable[None]],
):
    """22 §Live mounting: the first event reaches the old handler, the
    second the new one, and the subscription is the same object."""

    fired: list[str] = []
    dispatch = dispatch_handlers(bus, [_subscriber("old", fired)], PluginHost(store))
    subscription = dispatch.subscription
    assert subscription is not None
    try:
        bus.publish(_created("01J"))
        await wait_until(lambda: len(fired) == 1)

        dispatch.set("gamedev", _subscriber("new", fired))
        assert dispatch.subscription is subscription

        bus.publish(_created("01K"))
        await wait_until(lambda: len(fired) == 2)
    finally:
        await dispatch.aclose()

    assert fired == ["old:01J", "new:01K"]
    assert subscription.closed


async def test_set_to_none_drops_the_name_and_set_again_restores_it(
    store: Store,
    bus: EventBus,
    wait_until: Callable[[Callable[[], bool]], Awaitable[None]],
):
    fired: list[str] = []
    spec = _subscriber("one", fired)
    dispatch = dispatch_handlers(bus, [spec], PluginHost(store))
    subscription = dispatch.subscription
    try:
        dispatch.set("gamedev", None)
        assert dispatch.specs == {}
        assert dispatch.subscription is subscription
        bus.publish(_created("01J"))
        await asyncio.sleep(0.05)
        assert fired == []

        dispatch.set("gamedev", spec)
        assert dispatch.subscription is subscription
        bus.publish(_created("01K"))
        await wait_until(lambda: len(fired) == 1)
    finally:
        await dispatch.aclose()

    assert fired == ["one:01K"]


async def test_a_spec_without_handlers_is_not_kept_in_the_map(
    bus: EventBus,
):
    dispatch = dispatch_handlers(bus, [PluginSpec(workflow="gamedev")])
    try:
        assert dispatch.specs == {}
        dispatch.set("gamedev", PluginSpec(workflow="gamedev"))
        assert dispatch.specs == {}
    finally:
        await dispatch.aclose()


async def test_a_dispatcher_started_with_nothing_to_deliver_to_is_subscribed(
    store: Store,
    bus: EventBus,
    wait_until: Callable[[Callable[[], bool]], Awaitable[None]],
):
    """D236: the subscription is taken at start, so a spec with handlers
    that arrives later joins the one that already exists."""

    fired: list[str] = []
    dispatch = dispatch_handlers(bus, [], PluginHost(store))
    try:
        subscription = dispatch.subscription
        assert subscription is not None and not subscription.closed
        assert dispatch.running

        dispatch.set("gamedev", _subscriber("late", fired))
        assert dispatch.subscription is subscription
        bus.publish(_created("01J"))
        await wait_until(lambda: len(fired) == 1)
    finally:
        await dispatch.aclose()

    assert fired == ["late:01J"]
    assert dispatch.subscription is None
    assert not dispatch.running


async def test_a_handler_that_subscribes_to_nothing_that_fires_is_never_called(
    app_with: Callable[..., Awaitable[httpx.AsyncClient]],
    run_to_completion: Callable[[str], Awaitable[Any]],
):
    wf = Workflow("gamedev")
    fired: list[str] = []

    @wf.node(start=True)
    async def play():
        return None

    @wf.on("run.failed")
    async def failed(ctx: PluginContext, event: Event) -> None:
        fired.append(event.name)

    client = await app_with(wf, start=True)
    run_id = await submit(client)

    assert (await run_to_completion(run_id)).status == "completed"
    await asyncio.sleep(0.05)
    assert fired == []


# -- the host, directly -----------------------------------------------------


async def test_the_host_refuses_a_context_without_a_store():
    host = PluginHost(None)

    with pytest.raises(PluginError) as raised:
        await host.context(workflow="gamedev", run_id="whatever")

    assert raised.value.status == 500


async def test_ops_without_an_engine_refuses(store: Store):
    context = await PluginHost(store).context(workflow="gamedev")

    with pytest.raises(PluginError, match="no engine"):
        _ = context.ops


async def test_ops_is_the_engines(store: Store, engine: Engine):
    context = await PluginHost(store, engine).context(workflow="gamedev")

    assert context.ops is engine.ops


async def test_a_workflow_scoped_context_can_still_publish(store: Store):
    context = await PluginHost(store).context(workflow="gamedev")

    event = await context.services.events.publish("plugin.gamedev.scored", {"n": 1})

    assert (event.run_id, event.task_id) == (None, None)
    with pytest.raises(ValueError, match="not a plugin event"):
        await context.services.events.publish("run.completed", {})

"""Live mounting: a workflow's surface added, replaced and removed while
the application serves (T084, 22 §Live mounting).

Driven through `MountedPlugins` on a real, serving `create_app()` — the
`live_app` fixture — because what is under test is that Starlette matches
what the collection put on the router *now*: the route answers on the
next request, the manifest lists the entry, the asset is served with its
version, the handler joins the one subscription; and that removing takes
every one of those away without the subscription closing.

The fixture workflow of `tests/plugins/fixture_wf.py` is built under
several names, so the order tests have distinct entries that each carry
the whole surface.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from athanore.api.app import create_app
from athanore.engine import Engine
from athanore.engine.pools import Pool
from athanore.events.bus import EventBus
from athanore.plugins.builtin import builtin_spec
from athanore.plugins.mount import MountedPlugins
from athanore.plugins.registry import BUILTIN_WORKFLOW, PluginSpec, collect, validate
from athanore.settings import AthanoreSettings
from athanore.store.rows import EventRow, RunStatus
from athanore.store.uow import Store
from athanore.workflow import Workflow
from tests.plugins.fixture_wf import ELEMENT, fixture_workflow, recorded, rules_text

#: The fuse on every wait here. Reached only when something is broken.
DEADLINE = 5.0

#: How the manifest spells the fixture's one asset for a workflow.
ASSET = re.compile(r"^/plugins/(?P<wf>[a-z]+)/static/playfield\.js\?v=[0-9a-f]{12}$")

#: What `live_app` yields, spelled once.
LiveApp = tuple[FastAPI, httpx.AsyncClient]


def spec_of(name: str) -> PluginSpec:
    """The fixture workflow under ``name``, collected and validated."""

    wf = fixture_workflow(name)
    spec = collect(wf)
    validate(spec, wf.finalize())
    return spec


def registered(engine: Engine, settings: AthanoreSettings, name: str) -> PluginSpec:
    """``spec_of(name)``, with its graph registered so a run of it can go.

    The order T085's `Server.add` does the two in: the engine first,
    then the surface.
    """

    wf = fixture_workflow(name)
    graph = wf.finalize()
    spec = collect(wf)
    validate(spec, graph)
    engine.register(graph, Pool("test", settings.workers))
    return spec


async def manifest_order(client: httpx.AsyncClient) -> list[str]:
    """The workflows ``GET /api/plugins`` lists, in order."""

    response = await client.get("/api/plugins")
    assert response.status_code == 200, response.text
    return [entry["workflow"] for entry in response.json()]


async def entry_of(client: httpx.AsyncClient, workflow: str) -> dict[str, Any]:
    response = await client.get("/api/plugins")
    assert response.status_code == 200, response.text
    entries = [one for one in response.json() if one["workflow"] == workflow]
    assert entries, f"{workflow!r} is not in the manifest"
    return entries[0]


async def openapi_paths(client: httpx.AsyncClient) -> set[str]:
    response = await client.get("/openapi.json")
    assert response.status_code == 200, response.text
    return set(response.json()["paths"])


async def submit(client: httpx.AsyncClient, workflow: str) -> str:
    """Queue a run through the API, and return its id."""

    response = await client.post(
        f"/api/workflows/{workflow}/runs", json={"title": "a round"}
    )
    assert response.status_code == 201, response.text
    return response.json()["run_id"]


async def completed(store: Store, run_id: str) -> None:
    """Wait for the run to complete, by polling the store."""

    async with asyncio.timeout(DEADLINE):
        while True:
            async with store.reader() as reader:
                row = await reader.runs.get(run_id)
            if row is not None and row.status is RunStatus.completed:
                return
            await asyncio.sleep(0.01)


async def stored_events(store: Store, run_id: str) -> list[EventRow]:
    async with store.reader() as reader:
        return list(await reader.events.list_for_run(run_id))


async def wait_for_event(store: Store, run_id: str, name: str) -> EventRow:
    """The run's stored event called ``name``, once there is one."""

    async with asyncio.timeout(DEADLINE):
        while True:
            found = [
                row for row in await stored_events(store, run_id) if row.name == name
            ]
            if found:
                return found[-1]
            await asyncio.sleep(0.01)


def route_names(app: FastAPI, workflow: str) -> list[str]:
    """Every route on the router that belongs to ``workflow``.

    FastAPI includes a router as one entry that refers to it, so the
    names are one level down; a route carried flat is read as well.
    """

    prefix = f"plugin:{workflow}:"
    names: list[str] = []
    for entry in app.router.routes:
        included = getattr(entry, "original_router", None)
        routes = included.routes if included is not None else [entry]
        for route in routes:
            name = getattr(route, "name", None)
            if isinstance(name, str) and name.startswith(prefix):
                names.append(name)
    return names


def plugins_of(app: FastAPI) -> MountedPlugins:
    plugins = app.state.plugins
    assert isinstance(plugins, MountedPlugins)
    return plugins


# -- add --------------------------------------------------------------------


async def test_a_spec_added_while_serving_answers_on_every_surface(
    live_app: LiveApp, engine: Engine, settings: AthanoreSettings, store: Store
) -> None:
    """22 §Live mounting, §Testing (*Plugins*): route, manifest, asset,
    action, workflow view, document, handler — all on the next request."""

    app, client = live_app
    plugins = plugins_of(app)
    assert await manifest_order(client) == [BUILTIN_WORKFLOW]
    assert (await client.get("/api/plugins/gamedev/rules")).status_code == 404

    plugins.add(registered(engine, settings, "gamedev"))

    # the route
    response = await client.get("/api/plugins/gamedev/rules")
    assert response.status_code == 200, response.text
    assert response.json() == rules_text("gamedev")

    # the manifest: after the entries already there, with the version
    assert await manifest_order(client) == [BUILTIN_WORKFLOW, "gamedev"]
    entry = await entry_of(client, "gamedev")
    assert len(entry["assets"]) == 1
    assert ASSET.match(entry["assets"][0]), entry["assets"]
    assert entry["panels"], "the panels are in the entry"

    # the asset, at the URL the manifest listed
    asset = await client.get(entry["assets"][0])
    assert asset.status_code == 200
    assert f'customElements.define("{ELEMENT}"' in asset.text

    # the action: found (and refused on its input), not 404
    action = await client.post(
        "/api/plugins/gamedev/actions/override", json={"input": {}}
    )
    assert action.status_code == 422, action.text

    # the workflow view carries the same panels
    view = await client.get("/api/workflows/gamedev")
    assert view.status_code == 200, view.text
    assert [panel["name"] for panel in view.json()["plugin"]["panels"]] == [
        panel["name"] for panel in entry["panels"]
    ]

    # the document describes the route that now exists
    assert "/api/plugins/gamedev/rules" in await openapi_paths(client)

    # the `on` handler joined the dispatcher: the next `run.completed`
    # reaches it, and what it publishes is on the run
    run_id = await submit(client, "gamedev")
    await completed(store, run_id)
    event = await wait_for_event(store, run_id, recorded("gamedev"))
    assert event.data["on"] == "run.completed"


async def test_add_refuses_a_workflow_already_held(
    live_app: LiveApp, engine: Engine, settings: AthanoreSettings
) -> None:
    app, client = live_app
    plugins = plugins_of(app)
    plugins.add(registered(engine, settings, "gamedev"))

    with pytest.raises(ValueError, match="already mounted"):
        plugins.add(spec_of("gamedev"))

    assert await manifest_order(client) == [BUILTIN_WORKFLOW, "gamedev"]
    held = plugins.get("gamedev")
    assert held is not None
    assert len(route_names(app, "gamedev")) == len(held.routes)


# -- remove -----------------------------------------------------------------


async def test_a_spec_removed_while_serving_is_gone_from_every_surface(
    live_app: LiveApp, engine: Engine, settings: AthanoreSettings, store: Store
) -> None:
    """22 §Remove step 3: 404 `not_found` on the routes, no entry, no
    asset, no action, no handler — and the document agrees."""

    app, client = live_app
    plugins = plugins_of(app)
    spec = registered(engine, settings, "gamedev")
    plugins.add(spec)
    asset_url = (await entry_of(client, "gamedev"))["assets"][0]
    assert plugins.dispatch is not None and "gamedev" in plugins.dispatch.specs

    assert plugins.remove("gamedev") is spec

    # the API's own 404, not Starlette's `{"detail": …}`
    response = await client.get("/api/plugins/gamedev/rules")
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"
    assert await manifest_order(client) == [BUILTIN_WORKFLOW]
    asset = await client.get(asset_url)
    assert asset.status_code == 404
    assert asset.json()["code"] == "not_found"
    action = await client.post(
        "/api/plugins/gamedev/actions/override", json={"input": {}}
    )
    assert action.status_code == 404
    assert "/api/plugins/gamedev/rules" not in await openapi_paths(client)
    assert route_names(app, "gamedev") == []
    assert not any(
        getattr(route, "path", None) == "/plugins/gamedev/static"
        for route in app.router.routes
    )
    assert "gamedev" not in plugins.dispatch.specs
    assert plugins.get("gamedev") is None

    # the graph is still registered — T085's `remove` is what takes it
    # off the engine — so a run of it still completes; its handler is
    # not there to see the event
    run_id = await submit(client, "gamedev")
    await completed(store, run_id)
    await asyncio.sleep(0.1)
    assert recorded("gamedev") not in {
        row.name for row in await stored_events(store, run_id)
    }

    # a second remove is a no-op, not an error
    assert plugins.remove("gamedev") is None


async def test_the_subscription_is_the_same_one_across_every_mutation(
    live_app: LiveApp, engine: Engine, settings: AthanoreSettings
) -> None:
    """22 §Live mounting: no event is missed across a swap, because the
    swap never closes the subscription."""

    app, _ = live_app
    plugins = plugins_of(app)
    dispatch = plugins.dispatch
    assert dispatch is not None
    subscription = dispatch.subscription
    assert subscription is not None and not subscription.closed
    assert dispatch.running

    plugins.add(registered(engine, settings, "gamedev"))
    assert dispatch.subscription is subscription
    plugins.remove("gamedev")
    assert dispatch.subscription is subscription
    plugins.add(spec_of("gamedev"))
    assert dispatch.subscription is subscription
    plugins.replace(spec_of("gamedev"))
    assert dispatch.subscription is subscription

    assert not subscription.closed
    assert dispatch.running


async def test_the_second_of_two_events_straddling_a_swap_reaches_the_new_handler(
    live_app: LiveApp, engine: Engine, settings: AthanoreSettings, store: Store
) -> None:
    """A run completed before the swap reached the old handler; one
    completed after it reaches the new one — on the one subscription."""

    app, client = live_app
    plugins = plugins_of(app)
    plugins.add(registered(engine, settings, "gamedev"))
    first = await submit(client, "gamedev")
    await completed(store, first)
    await wait_for_event(store, first, recorded("gamedev"))

    plugins.replace(spec_of("gamedev"))

    second = await submit(client, "gamedev")
    await completed(store, second)
    await wait_for_event(store, second, recorded("gamedev"))


# -- replace ----------------------------------------------------------------


async def test_replace_keeps_the_position_in_the_manifest(
    live_app: LiveApp, engine: Engine, settings: AthanoreSettings
) -> None:
    """22 §Replace step 2: same position, same prefix, the new routes."""

    app, client = live_app
    plugins = plugins_of(app)
    for name in ("alpha", "beta", "gamma"):
        plugins.add(registered(engine, settings, name))
    assert await manifest_order(client) == [BUILTIN_WORKFLOW, "alpha", "beta", "gamma"]
    old = plugins.get("beta")
    before = len(route_names(app, "beta"))

    new = spec_of("beta")
    plugins.replace(new)

    assert await manifest_order(client) == [BUILTIN_WORKFLOW, "alpha", "beta", "gamma"]
    assert plugins.get("beta") is new
    assert plugins.get("beta") is not old
    # the new routes, and only once: the old ones were taken down
    assert len(route_names(app, "beta")) == before
    response = await client.get("/api/plugins/beta/rules")
    assert response.status_code == 200, response.text
    assert response.json() == rules_text("beta")
    assert (await client.get("/api/plugins/alpha/rules")).status_code == 200
    assert (await client.get("/api/plugins/gamma/rules")).status_code == 200
    assert "/api/plugins/beta/rules" in await openapi_paths(client)


async def test_replace_of_a_name_never_held_appends(
    live_app: LiveApp, engine: Engine, settings: AthanoreSettings
) -> None:
    """A workflow that declared nothing before may declare something now."""

    app, client = live_app
    plugins = plugins_of(app)
    plugins.add(registered(engine, settings, "alpha"))

    plugins.replace(spec_of("delta"))

    assert await manifest_order(client) == [BUILTIN_WORKFLOW, "alpha", "delta"]
    assert (await client.get("/api/plugins/delta/rules")).status_code == 200


async def test_replace_with_an_empty_spec_removes(
    live_app: LiveApp, engine: Engine, settings: AthanoreSettings
) -> None:
    """The new code declares nothing: the old surface goes, nothing is held."""

    app, client = live_app
    plugins = plugins_of(app)
    plugins.add(registered(engine, settings, "alpha"))
    plugins.add(registered(engine, settings, "beta"))

    plugins.replace(PluginSpec(workflow="alpha"))

    assert await manifest_order(client) == [BUILTIN_WORKFLOW, "beta"]
    assert plugins.get("alpha") is None
    assert route_names(app, "alpha") == []
    response = await client.get("/api/plugins/alpha/rules")
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


# -- an empty spec, and the builtin entry --------------------------------------


async def test_an_empty_spec_is_held_nowhere(live_app: LiveApp) -> None:
    """09 §Wire contract: a workflow that declares nothing has no entry,
    and the caller does not have to know that to call `add`."""

    app, client = live_app
    plugins = plugins_of(app)
    wf = Workflow("bare")

    @wf.node(start=True)
    async def only() -> None:
        return None

    spec = collect(wf)
    validate(spec, wf.finalize())
    assert not spec
    paths = await openapi_paths(client)

    plugins.add(spec)

    assert await manifest_order(client) == [BUILTIN_WORKFLOW]
    assert plugins.get("bare") is None
    assert plugins.specs == (plugins.get(BUILTIN_WORKFLOW),)
    assert await openapi_paths(client) == paths
    assert plugins.remove("bare") is None


async def test_the_builtin_entry_is_first_throughout_and_cannot_go(
    live_app: LiveApp, engine: Engine, settings: AthanoreSettings
) -> None:
    app, client = live_app
    plugins = plugins_of(app)

    with pytest.raises(ValueError, match="cannot be removed"):
        plugins.remove(BUILTIN_WORKFLOW)
    with pytest.raises(ValueError, match="cannot be replaced"):
        plugins.replace(builtin_spec())

    plugins.add(registered(engine, settings, "alpha"))
    assert (await manifest_order(client))[0] == BUILTIN_WORKFLOW
    plugins.replace(spec_of("alpha"))
    assert (await manifest_order(client))[0] == BUILTIN_WORKFLOW
    plugins.remove("alpha")
    assert await manifest_order(client) == [BUILTIN_WORKFLOW]
    assert plugins.specs[0].workflow == BUILTIN_WORKFLOW


# -- specs is a snapshot; no engine -------------------------------------------


async def test_specs_is_a_fresh_tuple_per_call(
    live_app: LiveApp, engine: Engine, settings: AthanoreSettings
) -> None:
    """A reader holding a snapshot cannot see a mutation land under it."""

    app, _ = live_app
    plugins = plugins_of(app)
    snapshot = plugins.specs

    plugins.add(registered(engine, settings, "alpha"))

    assert [spec.workflow for spec in snapshot] == [BUILTIN_WORKFLOW]
    assert [spec.workflow for spec in plugins.specs] == [BUILTIN_WORKFLOW, "alpha"]
    assert plugins.specs is not snapshot


async def test_without_an_engine_routes_still_mount_and_unmount(
    settings: AthanoreSettings, store: Store, bus: EventBus
) -> None:
    """No engine means no bus and no dispatcher; the routes and the
    assets mount come and go all the same."""

    spec = spec_of("gamedev")
    app = create_app(settings=settings, store=store, plugins=[spec])
    plugins = plugins_of(app)
    assert plugins.dispatch is None
    assert plugins.specs == (spec,)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        assert (await client.get("/api/plugins/gamedev/rules")).status_code == 200
        asset_url = (await entry_of(client, "gamedev"))["assets"][0]
        assert ASSET.match(asset_url)
        assert (await client.get(asset_url)).status_code == 200

        assert plugins.remove("gamedev") is spec

        assert (await client.get("/api/plugins/gamedev/rules")).status_code == 404
        assert (await client.get(asset_url)).status_code == 404
        assert await manifest_order(client) == []

        plugins.add(spec_of("gamedev"))

        assert (await client.get("/api/plugins/gamedev/rules")).status_code == 200
        assert (await client.get(asset_url)).status_code == 200

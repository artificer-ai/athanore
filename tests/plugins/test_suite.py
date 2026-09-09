"""The plugin suite: 09, end to end, over one workflow that uses all of it.

`tests/plugins/fixture_wf.py` declares one of everything the plugin
vocabulary offers. This file drives it through a real ``create_app()``
and asserts the five properties 17 §T073 names:

- **the manifest is complete** — every declaration is on the wire, in
  declaration order, carrying the JSON Schema of a *nested* model, and
  every ``source`` it names answers with the shape its ``kind`` promises;
- **the route and the action 404 on a foreign run** — never 403, because
  whether a run exists is not something one workflow's plugin learns
  about another's (09 §Context and scopes);
- **node liveness flips with task state** — the ``node``-slot pane the
  SPA shows is the manifest entry's node being ``live`` in the *selected
  run's* graph, so one static manifest yields a pane on a run that has
  reached the node and none on a run that has not (08 §Graph semantics,
  09 §Slots);
- **``on`` fires after commit** — the handler reads the run back out of
  the store and finds the status the event announced already durable;
- **the asset is served with the CSP** of 12 §Plugins.

The other suites in this directory each take one mechanism apart. This
one asks whether the mechanisms compose: an author who writes the fixture
gets a working pane, form, element and subscription, or the vocabulary
has a hole.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

import httpx

from athanore.api import static
from athanore.engine import Engine
from athanore.plugins.decl import PLACEMENTS, PanelKind, Slot
from athanore.plugins.registry import collect
from athanore.store.rows import EventRow
from athanore.store.uow import Store
from tests.plugins.fixture_wf import (
    ELEMENT,
    NODE_COLUMNS,
    SECRET,
    WORD_COLUMNS,
    WORKFLOW,
    fixture_workflow,
    overridden,
    recorded,
    rules_text,
)

#: The fuse on every wait here. Reached only when something is broken.
DEADLINE = 5.0

#: The one asset the fixture ships, as the manifest spells it.
ASSET_URL = f"/plugins/{WORKFLOW}/static/playfield.js"

#: A well-formed run id that names no run.
MISSING_RUN = "01JQNOTAREALRUNID0000000"

#: The run the fixture's graph produces, once ``judge`` has scored it.
OUTPUT = {"word": SECRET, "score": len(SECRET)}

#: What ``app_with`` is, spelled once.
AppFactory = Callable[..., Awaitable[httpx.AsyncClient]]

#: Every panel the fixture declares, in declaration order, exactly as
#: ``GET /api/plugins`` renders it. Written out rather than derived: a
#: manifest assembled from the same declarations it is checked against
#: would agree with itself no matter what either of them said.
PANELS: list[dict[str, Any]] = [
    {
        "name": "How to play",
        "slot": "workflow",
        "placement": "pane",
        "kind": "markdown",
        "scope": "workflow",
        "source": f"/api/plugins/{WORKFLOW}/rules",
        "refresh_on": [],
    },
    {
        "name": "Round",
        "slot": "run",
        "placement": "card",
        "kind": "kv",
        "scope": "run",
        "source": f"/api/plugins/{WORKFLOW}/round",
        "refresh_on": ["run.*"],
    },
    {
        "name": "Words",
        "slot": "run",
        "placement": "pane",
        "kind": "table",
        "scope": "run",
        "source": f"/api/plugins/{WORKFLOW}/words",
        "refresh_on": ["log.appended"],
    },
    {
        "name": "History",
        "slot": "run",
        "placement": "pane",
        "kind": "log",
        "scope": "run",
        "source": f"/api/plugins/{WORKFLOW}/history",
        "refresh_on": ["task.*", "log.appended"],
    },
    {
        "name": "Scores",
        "slot": "run",
        "placement": "pane",
        "kind": "chart",
        "scope": "run",
        "source": f"/api/plugins/{WORKFLOW}/scores",
        "refresh_on": ["task.done"],
    },
    {
        "name": "Summary",
        "slot": "run",
        "placement": "pane",
        "kind": "dashboard",
        "scope": "run",
        "source": f"/api/plugins/{WORKFLOW}/summary",
        "refresh_on": ["run.*"],
    },
    {
        "name": "Override",
        "slot": "task",
        "placement": "pane",
        "kind": "form",
        "scope": "task",
        "source": "override",
        "refresh_on": [],
    },
    {
        "name": "Playfield",
        "slot": "global",
        "placement": "pane",
        "kind": "custom",
        "scope": "global",
        "element": ELEMENT,
        "refresh_on": [],
    },
    {
        "name": "Verdict",
        "slot": "node",
        "placement": "pane",
        "kind": "kv",
        "scope": "node",
        "node": "judge",
        "source": f"/api/plugins/{WORKFLOW}/verdict",
        "refresh_on": ["task.done"],
    },
]


# -- helpers ----------------------------------------------------------------


async def submit(
    client: httpx.AsyncClient, workflow: str = WORKFLOW, *, description: str = ""
) -> str:
    """Queue a run through the API, and return its id."""

    response = await client.post(
        f"/api/workflows/{workflow}/runs",
        json={"title": "a round", "description": description},
    )
    assert response.status_code == 201, response.text
    return response.json()["run_id"]


async def first_task(store: Store, run_id: str) -> int:
    """The id of the run's start task."""

    async with store.reader() as reader:
        tasks = await reader.tasks.list_for_run(run_id)
    assert tasks, "the run has no tasks"
    return tasks[0].id


async def entry_of(client: httpx.AsyncClient, workflow: str) -> dict[str, Any]:
    """One workflow's manifest entry, off the wire."""

    response = await client.get("/api/plugins")
    assert response.status_code == 200, response.text
    entries = [entry for entry in response.json() if entry["workflow"] == workflow]
    assert entries, f"{workflow!r} is not in the manifest"
    return entries[0]


async def graph_of(client: httpx.AsyncClient, run_id: str) -> dict[str, Any]:
    """``GET /api/runs/{id}/graph``, where liveness is computed."""

    response = await client.get(f"/api/runs/{run_id}/graph")
    assert response.status_code == 200, response.text
    return response.json()


def liveness(graph: Mapping[str, Any]) -> dict[str, bool]:
    """Which nodes of a run's graph are live, by name."""

    return {node["name"]: node["live"] for node in graph["nodes"]}


def node_panes(entry: Mapping[str, Any], graph: Mapping[str, Any]) -> list[str]:
    """The ``node``-slot panes the SPA shows for this run.

    The rule of 09 §Slots, applied here rather than asserted about: a
    ``node``-slot entry of the *static* manifest is shown when its node
    is ``live`` in the selected run's graph.
    """

    live = liveness(graph)
    return [
        panel["name"]
        for panel in entry["panels"]
        if panel["slot"] == Slot.node.value and live.get(panel.get("node", ""), False)
    ]


def params_for(panel: Mapping[str, Any], run_id: str) -> dict[str, str]:
    """The query a panel's ``source`` is fetched with, from its scope."""

    if panel["scope"] in (Slot.workflow.value, Slot.global_.value):
        return {}
    params = {"run_id": run_id}
    if "node" in panel:
        params["node"] = panel["node"]
    return params


def has_shape(kind: str, body: Any) -> bool:
    """Does ``body`` match the data shape 09 §Panel kinds gives ``kind``?"""

    match PanelKind(kind):
        case PanelKind.markdown:
            return isinstance(body, str)
        case PanelKind.kv:
            return isinstance(body, dict)
        case PanelKind.table:
            return (
                isinstance(body, dict)
                and isinstance(body.get("columns"), list)
                and isinstance(body.get("rows"), list)
                and all("key" in column for column in body["columns"])
            )
        case PanelKind.log:
            return isinstance(body, list) and all(
                {"ts", "text"} <= set(row) for row in body
            )
        case PanelKind.chart:
            return (
                isinstance(body, dict)
                and body.get("kind") in ("line", "bar")
                and all({"name", "points"} <= set(series) for series in body["series"])
            )
        case PanelKind.dashboard:
            return (
                isinstance(body, dict)
                and isinstance(body.get("metrics"), list)
                and set(body) <= {"note", "metrics", "table"}
            )
        case _:  # `form` and `custom` name no route, so nothing is fetched
            return False


async def wait_for_event(store: Store, run_id: str, name: str) -> EventRow:
    """The run's stored event called ``name``, once there is one."""

    async with asyncio.timeout(DEADLINE):
        while True:
            async with store.reader() as reader:
                stored = await reader.events.list_for_run(run_id)
            found = [row for row in stored if row.name == name]
            if found:
                return found[-1]
            await asyncio.sleep(0.01)


# -- the manifest is complete -----------------------------------------------


async def test_the_manifest_carries_every_panel_in_declaration_order(
    app_with: AppFactory,
) -> None:
    """09 §Wire contract, for the whole of one workflow's surface."""

    client = await app_with(fixture_workflow())

    entry = await entry_of(client, WORKFLOW)

    assert entry["panels"] == PANELS


async def test_the_manifest_carries_the_action_and_its_nested_form(
    app_with: AppFactory,
) -> None:
    """ "The model **is** the form", and this one nests."""

    client = await app_with(fixture_workflow())

    entry = await entry_of(client, WORKFLOW)

    assert len(entry["actions"]) == 1
    action = entry["actions"][0]
    assert (action["name"], action["title"]) == (
        "override",
        "Override the secret word",
    )
    assert (action["scope"], action["confirm"]) == ("task", True)
    schema = action["schema"]
    assert schema["required"] == ["word", "reason"]
    assert schema["properties"]["reason"]["$ref"] == "#/$defs/Reason"
    assert schema["$defs"]["Reason"]["properties"]["weight"] == {
        "default": 1,
        "description": "How strongly.",
        "maximum": 5,
        "minimum": 1,
        "title": "Weight",
        "type": "integer",
    }


async def test_the_manifest_lists_the_one_asset_the_workflow_ships(
    app_with: AppFactory,
) -> None:
    client = await app_with(fixture_workflow())

    entry = await entry_of(client, WORKFLOW)

    assert entry["assets"] == [ASSET_URL]


def test_the_fixture_uses_every_kind_every_slot_and_both_placements() -> None:
    """The claim T073 is for: nothing in the vocabulary is unexpressible.

    Read off the declarations rather than the wire, because what is under
    test is the *vocabulary* — a member no fixture can produce is a hole
    whether or not the manifest would have rendered it.
    """

    spec = collect(fixture_workflow())

    assert {panel.kind for panel in spec.panels} == set(PanelKind)
    assert {panel.slot for panel in spec.panels} == set(Slot)
    assert {panel.placement for panel in spec.panels} == PLACEMENTS
    assert {action.scope for action in spec.actions} == {Slot.task}
    assert [route.methods for route in spec.routes].count(("POST",)) == 1
    assert [handler.event for handler in spec.handlers] == ["run.completed"]


async def test_every_source_the_manifest_names_answers_in_its_kinds_shape(
    app_with: AppFactory,
    engine: Engine,
    run_to_completion: Callable[[str], Awaitable[Any]],
) -> None:
    """A complete manifest is one whose every declaration actually works.

    Each panel is fetched exactly as the SPA would fetch it — the URL the
    manifest gave, with the ids its scope calls for — and the body is
    checked against the shape 09 §Panel kinds promises for its ``kind``.
    A ``form`` names an action rather than a URL and a ``custom`` names
    none at all, so those two are checked for what they do carry.
    """

    client = await app_with(fixture_workflow(), start=True)
    run_id = await submit(client, description="a note for the dashboard")
    await run_to_completion(run_id)
    entry = await entry_of(client, WORKFLOW)

    fetched: list[str] = []
    for panel in entry["panels"]:
        if panel["kind"] == PanelKind.form.value:
            assert panel["source"] == "override"
            continue
        if panel["kind"] == PanelKind.custom.value:
            assert "source" not in panel and panel["element"] == ELEMENT
            continue
        response = await client.get(panel["source"], params=params_for(panel, run_id))
        assert response.status_code == 200, (panel["name"], response.text)
        assert has_shape(panel["kind"], response.json()), panel["name"]
        fetched.append(panel["name"])

    assert fetched == [
        "How to play",
        "Round",
        "Words",
        "History",
        "Scores",
        "Summary",
        "Verdict",
    ]


async def test_the_panels_draw_what_the_run_actually_did(
    app_with: AppFactory,
    run_to_completion: Callable[[str], Awaitable[Any]],
) -> None:
    """The shapes are right; these are the values inside them."""

    client = await app_with(fixture_workflow(), start=True)
    run_id = await submit(client, description="a note for the dashboard")
    await run_to_completion(run_id)

    rules = await client.get(f"/api/plugins/{WORKFLOW}/rules")
    assert rules.json() == rules_text(WORKFLOW)

    round_ = await client.get(
        f"/api/plugins/{WORKFLOW}/round", params={"run_id": run_id}
    )
    assert round_.json() == {
        "Run": "a round",
        "Status": "completed",
        "Word": SECRET,
        "Score": len(SECRET),
    }

    summary = await client.get(
        f"/api/plugins/{WORKFLOW}/summary", params={"run_id": run_id}
    )
    assert summary.json() == {
        "metrics": [{"label": "ATTEMPTS", "value": 2}],
        "table": {
            "columns": NODE_COLUMNS,
            "rows": [
                {"node": "play", "status": "done"},
                {"node": "judge", "status": "done"},
            ],
        },
        "note": "a note for the dashboard",
    }

    verdict = await client.get(
        f"/api/plugins/{WORKFLOW}/verdict",
        params={"run_id": run_id, "node": "judge"},
    )
    assert verdict.json() == {
        "Node": "judge",
        "Attempts": 1,
        "Status": "done",
        "Result": OUTPUT,
    }


async def test_a_routes_own_parameter_is_an_ordinary_fastapi_one(
    app_with: AppFactory, store: Store
) -> None:
    """``limit`` is parsed, defaulted and documented without the plugin."""

    client = await app_with(fixture_workflow())
    run_id = await submit(client)
    task_id = await first_task(store, run_id)
    for word in ("first", "second"):
        await call_override(client, task_id, word)

    whole = await client.get(
        f"/api/plugins/{WORKFLOW}/words", params={"run_id": run_id}
    )
    assert [row["word"] for row in whole.json()["rows"]] == ["first", "second"]
    assert whole.json()["columns"] == WORD_COLUMNS

    tail = await client.get(
        f"/api/plugins/{WORKFLOW}/words", params={"run_id": run_id, "limit": 1}
    )
    assert [row["word"] for row in tail.json()["rows"]] == ["second"]

    refused = await client.get(
        f"/api/plugins/{WORKFLOW}/words", params={"run_id": run_id, "limit": "many"}
    )
    assert refused.status_code == 422
    assert refused.json()["code"] == "validation"


async def test_the_document_carries_every_route_under_the_operator_door(
    app_with: AppFactory,
) -> None:
    """09 §Mounting: a plugin does not get an auth model of its own."""

    client = await app_with(fixture_workflow())
    document = (await client.get("/openapi.json")).json()

    paths = document["paths"]
    for path in (
        f"/api/plugins/{WORKFLOW}/rules",
        f"/api/plugins/{WORKFLOW}/verdict",
        f"/api/plugins/{WORKFLOW}/guess",
    ):
        operation = next(iter(paths[path].values()))
        assert operation["security"] == [{"operatorBearer": []}]
        assert operation["tags"] == ["plugins"]
        assert {parameter["name"] for parameter in operation["parameters"]} >= {
            "run_id",
            "task_id",
            "node",
        }
    assert set(paths[f"/api/plugins/{WORKFLOW}/guess"]) == {"post"}


# -- the route and the action 404 on a foreign run --------------------------


async def call_override(
    client: httpx.AsyncClient,
    task_id: int | None = None,
    word: str = "orpiment",
    *,
    workflow: str = WORKFLOW,
    run_id: str | None = None,
    reason: Any = None,
) -> httpx.Response:
    """Invoke the fixture's action, at whatever scope was asked for."""

    scope: dict[str, Any] = {}
    if run_id is not None:
        scope["run_id"] = run_id
    if task_id is not None:
        scope["task_id"] = task_id
    return await client.post(
        f"/api/plugins/{workflow}/actions/override",
        json={
            "scope": scope,
            "input": {
                "word": word,
                "reason": {"text": "the word was taken"} if reason is None else reason,
            },
        },
    )


async def test_a_route_404s_on_another_workflows_run(app_with: AppFactory) -> None:
    """09 §Context and scopes: a 404, and never a 403."""

    client = await app_with(fixture_workflow(), fixture_workflow("other"))
    theirs = await submit(client, "other")

    response = await client.get(
        f"/api/plugins/{WORKFLOW}/round", params={"run_id": theirs}
    )

    assert response.status_code == 404
    assert response.json()["code"] == "plugin_error"
    assert "belongs to workflow 'other'" in response.json()["error"]


async def test_an_action_404s_on_another_workflows_run(
    app_with: AppFactory, store: Store
) -> None:
    client = await app_with(fixture_workflow(), fixture_workflow("other"))
    theirs = await submit(client, "other")

    response = await call_override(
        client, await first_task(store, theirs), run_id=theirs
    )

    assert response.status_code == 404
    assert response.json()["code"] == "plugin_error"
    assert "403" not in response.text


async def test_a_route_and_an_action_404_on_a_run_that_does_not_exist(
    app_with: AppFactory,
) -> None:
    client = await app_with(fixture_workflow())

    route = await client.get(
        f"/api/plugins/{WORKFLOW}/round", params={"run_id": MISSING_RUN}
    )
    action = await call_override(client, run_id=MISSING_RUN)

    assert route.status_code == 404
    assert action.status_code == 404


async def test_a_route_and_an_action_404_on_a_task_of_another_run(
    app_with: AppFactory, store: Store
) -> None:
    client = await app_with(fixture_workflow())
    mine = await submit(client)
    other = await submit(client)
    foreign = await first_task(store, other)

    route = await client.get(
        f"/api/plugins/{WORKFLOW}/round",
        params={"run_id": mine, "task_id": foreign},
    )
    action = await call_override(client, foreign, run_id=mine)

    assert route.status_code == 404
    assert "does not belong to run" in route.json()["error"]
    assert action.status_code == 404


async def test_one_workflows_assets_and_actions_are_not_anothers(
    app_with: AppFactory,
) -> None:
    """Scope follows ownership, for files and for endpoints alike."""

    client = await app_with(fixture_workflow())

    assert (await client.get("/plugins/other/static/playfield.js")).status_code == 404
    assert (await call_override(client, workflow="other")).status_code == 404


# -- node liveness flips with task state ------------------------------------


async def test_the_node_pane_appears_only_once_its_node_is_live(
    app_with: AppFactory,
    engine: Engine,
    run_to_completion: Callable[[str], Awaitable[Any]],
) -> None:
    """08 §Graph semantics and 09 §Slots, together.

    The manifest is fetched once and never again: what changes is the
    run's graph. Before the engine runs anything, ``judge`` has no task
    and the pane is not shown; once the run has been through it, the same
    manifest entry yields the pane.
    """

    client = await app_with(fixture_workflow())
    run_id = await submit(client)
    entry = await entry_of(client, WORKFLOW)

    queued = await graph_of(client, run_id)
    assert liveness(queued) == {"play": False, "judge": False}
    assert node_panes(entry, queued) == []

    await engine.start()
    await run_to_completion(run_id)

    finished = await graph_of(client, run_id)
    assert liveness(finished) == {"play": True, "judge": True}
    assert node_panes(entry, finished) == ["Verdict"]


async def test_the_same_manifest_shows_the_pane_on_one_run_and_not_another(
    app_with: AppFactory,
    engine: Engine,
    run_to_completion: Callable[[str], Awaitable[Any]],
) -> None:
    """Liveness is per run, which is why the manifest can stay static."""

    client = await app_with(fixture_workflow())
    finished_run = await submit(client)
    await engine.start()
    await run_to_completion(finished_run)
    await engine.stop()
    queued_run = await submit(client)
    entry = await entry_of(client, WORKFLOW)

    assert node_panes(entry, await graph_of(client, finished_run)) == ["Verdict"]
    assert node_panes(entry, await graph_of(client, queued_run)) == []


async def test_the_node_route_refuses_where_no_node_was_named(
    app_with: AppFactory,
) -> None:
    """A pane about a node nobody named has nothing to draw."""

    client = await app_with(fixture_workflow())
    run_id = await submit(client)

    response = await client.get(
        f"/api/plugins/{WORKFLOW}/verdict", params={"run_id": run_id}
    )

    assert response.status_code == 400
    assert response.json() == {"error": "no node in scope", "code": "plugin_error"}


async def test_a_node_the_workflow_does_not_have_is_404(
    app_with: AppFactory,
) -> None:
    client = await app_with(fixture_workflow())
    run_id = await submit(client)

    response = await client.get(
        f"/api/plugins/{WORKFLOW}/verdict", params={"run_id": run_id, "node": "nope"}
    )

    assert response.status_code == 404
    assert "has no node 'nope'" in response.json()["error"]


# -- `on` fires after commit ------------------------------------------------


async def test_the_on_handler_reads_the_run_the_event_announced(
    app_with: AppFactory,
    store: Store,
    run_to_completion: Callable[[str], Awaitable[Any]],
) -> None:
    """09 §Mounting: the bus is fed by the outbox *after* the commit.

    The handler does not trust the payload — it reads the run back out of
    the store and publishes what it found. Finding ``completed`` and the
    terminal node's output there is the whole claim: a handler called
    inside the emitting transaction would have read a run still in
    progress, and one called before the outbox drained would have read
    nothing at all.
    """

    client = await app_with(fixture_workflow(), start=True)
    run_id = await submit(client)
    assert (await run_to_completion(run_id)).status == "completed"

    event = await wait_for_event(store, run_id, recorded(WORKFLOW))

    assert event.data == {
        "status": "completed",
        "output": OUTPUT,
        "on": "run.completed",
    }
    assert event.run_id == run_id


async def test_the_handler_of_another_workflow_is_not_called(
    app_with: AppFactory,
    store: Store,
    run_to_completion: Callable[[str], Awaitable[Any]],
) -> None:
    """Ownership decides who is called, one run at a time."""

    client = await app_with(fixture_workflow(), fixture_workflow("other"), start=True)
    mine = await submit(client)
    theirs = await submit(client, "other")
    await run_to_completion(theirs)
    await run_to_completion(mine)

    await wait_for_event(store, mine, recorded(WORKFLOW))
    await wait_for_event(store, theirs, recorded("other"))
    async with store.reader() as reader:
        names = {row.name for row in await reader.events.list_for_run(mine)}

    assert recorded("other") not in names


# -- the action, the element's route, and the events they publish -----------


async def test_the_action_validates_the_nested_model(
    app_with: AppFactory, store: Store
) -> None:
    """A misfit inside the nested model is the 422 of 08 §Conventions."""

    client = await app_with(fixture_workflow())
    run_id = await submit(client)
    task_id = await first_task(store, run_id)

    response = await call_override(client, task_id, reason={"text": "", "weight": 9})

    assert response.status_code == 422
    assert response.json()["code"] == "validation"
    assert [error["loc"] for error in response.json()["errors"]] == [
        ["reason", "text"],
        ["reason", "weight"],
    ]
    async with store.reader() as reader:
        assert await reader.log.list(run_id) == []


async def test_the_action_writes_the_log_and_publishes_in_its_own_namespace(
    app_with: AppFactory, store: Store
) -> None:
    client = await app_with(fixture_workflow())
    run_id = await submit(client)
    task_id = await first_task(store, run_id)

    response = await call_override(client, task_id, "orpiment")

    assert response.status_code == 200, response.text
    assert response.json()["word"] == "orpiment"
    assert response.json()["node"] == "play"
    async with store.reader() as reader:
        entries = await reader.log.list(run_id)
        events = await reader.events.list_for_run(run_id)
    assert [(entry.text, entry.author.value) for entry in entries] == [
        ("word: orpiment", "user")
    ]
    published = [row for row in events if row.name == overridden(WORKFLOW)]
    assert [row.data for row in published] == [
        {"word": "orpiment", "reason": "the word was taken", "weight": 1}
    ]
    assert published[0].task_id == task_id


async def test_the_action_needs_the_scope_it_declared(
    app_with: AppFactory,
) -> None:
    """A task-scoped action given only a run refuses one level in."""

    client = await app_with(fixture_workflow())
    run_id = await submit(client)

    response = await call_override(client, run_id=run_id)

    assert response.status_code == 400
    assert response.json() == {"error": "no task in scope", "code": "plugin_error"}


async def test_the_elements_route_takes_a_post_and_writes_the_transcript(
    app_with: AppFactory, store: Store
) -> None:
    """``methods=`` is what a custom element reaches its workflow with.

    The chunk is read back through the store rather than the transcript
    endpoint because what is being asserted is that the context's stream
    service was flushed when the request ended — the generator dependency
    of 09 §Mounting closing what the handler opened.
    """

    client = await app_with(fixture_workflow())
    run_id = await submit(client)
    task_id = await first_task(store, run_id)

    response = await client.post(
        f"/api/plugins/{WORKFLOW}/guess",
        params={"task_id": task_id},
        json={"word": SECRET},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"seq": 1, "correct": True}
    async with store.reader() as reader:
        chunks = await reader.stream.list_after(task_id)
    assert [(chunk.seq, chunk.kind, chunk.text) for chunk in chunks] == [
        (1, "notice", f"guess: {SECRET}")
    ]


# -- the asset is served with the CSP ---------------------------------------


async def test_the_asset_is_served_under_the_workflows_prefix_with_the_policy(
    app_with: AppFactory,
) -> None:
    """09 §Escape hatch and 12 §Plugins: the file, under the SPA's policy."""

    client = await app_with(fixture_workflow())

    response = await client.get(ASSET_URL)

    assert response.status_code == 200
    assert response.headers["content-security-policy"] == static.CSP
    assert f'customElements.define("{ELEMENT}"' in response.text


async def test_an_asset_that_is_not_there_is_the_apis_own_404(
    app_with: AppFactory,
) -> None:
    client = await app_with(fixture_workflow())

    response = await client.get(f"/plugins/{WORKFLOW}/static/nothing.js")

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"

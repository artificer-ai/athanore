"""The action endpoint: validation, scope, ownership, refusals (T070, 09).

`POST /api/plugins/{wf}/actions/{name}` is the one way an action is
invoked (09 §Wire contract), and every assertion here is made through a
real `create_app()` over ASGI, for the reason `test_mount.py` gives:
what is under test is the whole path — the operator door, the 422 the
model produces, the 404s ownership makes, and the shape a `PluginError`
comes back as.

Four properties, and they are the four the endpoint exists to have:

- **the server validates, every time.** The browser drew the form from
  the same schema; that is not a reason to trust what came back (12
  §Plugins). The refusal is 08 §Conventions' 422, and its `loc` paths
  are the model's, because the SPA maps them onto the form's fields.
- **scope follows ownership.** A `run_id` of another workflow is a 404
  before the handler runs, and never a 403.
- **a handler is never partially resolved.** A `run`-scoped action
  invoked with no run refuses in the wording its services would have
  used, one step earlier.
- **a handler says its own status.** `PluginError(409, …)` is a 409 with
  `code: "plugin_error"`, not a 500 and not a 400.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest
from pydantic import BaseModel, Field

from athanore.plugins.context import NO_NODE, NO_RUN, NO_TASK, PluginContext
from athanore.plugins.decl import PluginError
from athanore.store.uow import Store
from athanore.workflow import Workflow


class Override(BaseModel):
    """09 §Declarations' own example model, and therefore its own form."""

    word: str
    reason: str = ""
    weight: int = Field(default=1, ge=1)


def gamedev() -> Workflow:
    """One workflow, one action per scope, and one that refuses."""

    wf = Workflow("gamedev")

    @wf.node(start=True)
    async def play():
        """Play one round."""
        return {"word": "athanor"}

    @wf.action("override", title="Override secret word", confirm=True)
    async def override(ctx: PluginContext, input: Override) -> dict:
        """The run-scoped action of 09 §Declarations."""
        return {
            "workflow": ctx.workflow,
            "run_id": ctx.run_id,
            "task_id": ctx.task_id,
            "node": ctx.node,
            "title": ctx.run.title if ctx.run is not None else None,
            "word": input.word,
            "reason": input.reason,
            "weight": input.weight,
        }

    @wf.action("note", scope="task")
    async def note(ctx: PluginContext, input: Override) -> dict:
        """A task-scoped action, which writes the attempt's work log."""
        entry = await ctx.services.log.append(input.word, author="user")
        return {"log_id": entry.id, "task_id": ctx.task_id}

    @wf.action("watch", scope="node")
    async def watch(ctx: PluginContext) -> dict:
        """A node-scoped action, which takes no input at all."""
        return {"node": ctx.node, "run_id": ctx.run_id}

    @wf.action("sweep", scope="global")
    async def sweep(ctx: PluginContext) -> dict:
        """A global action: no run, and none needed."""
        runs = await ctx.services.run.list()
        return {"run_id": ctx.run_id, "runs": [run.id for run in runs]}

    @wf.action("refuse", scope="global")
    async def refuse(ctx: PluginContext) -> dict:
        """A handler that names the status it means (09 §Wire contract)."""
        raise PluginError(409, "the word has already been overridden")

    @wf.action("boom", scope="global")
    async def boom(ctx: PluginContext) -> dict:
        """A handler with a defect in it."""
        raise RuntimeError("the plugin is broken")

    @wf.action("plain", scope="global")
    def plain(ctx: PluginContext) -> dict:
        """A synchronous handler, which is called inline (09)."""
        return {"sync": True}

    return wf


def other() -> Workflow:
    """A second workflow, so ownership has something to be wrong about."""

    wf = Workflow("other")

    @wf.node(start=True)
    async def only():
        return None

    @wf.action("peek")
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


async def call(
    client: httpx.AsyncClient,
    name: str,
    *,
    workflow: str = "gamedev",
    scope: dict[str, Any] | None = None,
    payload: Any = None,
) -> httpx.Response:
    """`POST /api/plugins/{wf}/actions/{name}` with the body of 08."""

    return await client.post(
        f"/api/plugins/{workflow}/actions/{name}",
        json={"scope": scope or {}, "input": payload},
    )


# -- the happy path ---------------------------------------------------------


async def test_an_action_runs_with_its_scope_resolved(
    app_with: Callable[..., Awaitable[httpx.AsyncClient]],
):
    client = await app_with(gamedev())
    run_id = await submit(client)

    response = await call(
        client,
        "override",
        scope={"run_id": run_id},
        payload={"word": "crucible", "reason": "too easy"},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "workflow": "gamedev",
        "run_id": run_id,
        "task_id": None,
        "node": None,
        "title": "a run",
        "word": "crucible",
        "reason": "too easy",
        "weight": 1,
    }


async def test_a_task_scoped_action_writes_through_the_attempts_services(
    app_with: Callable[..., Awaitable[httpx.AsyncClient]], store: Store
):
    """The same services a node body gets, reached over HTTP (09)."""

    client = await app_with(gamedev())
    run_id = await submit(client)
    task_id = await first_task(store, run_id)

    response = await call(
        client, "note", scope={"task_id": task_id}, payload={"word": "a note"}
    )

    assert response.status_code == 200, response.text
    assert response.json()["task_id"] == task_id
    async with store.reader() as reader:
        entries = await reader.log.list(run_id)
    assert [(entry.text, entry.author, entry.node) for entry in entries] == [
        ("a note", "user", "play")
    ]


async def test_a_node_scoped_action_takes_the_node_from_the_task(
    app_with: Callable[..., Awaitable[httpx.AsyncClient]], store: Store
):
    """A node named outright, and a node that arrives with the attempt."""

    client = await app_with(gamedev())
    run_id = await submit(client)
    task_id = await first_task(store, run_id)

    named = await call(client, "watch", scope={"run_id": run_id, "node": "play"})
    assert named.status_code == 200, named.text
    assert named.json() == {"node": "play", "run_id": run_id}

    inherited = await call(client, "watch", scope={"task_id": task_id})
    assert inherited.status_code == 200, inherited.text
    assert inherited.json() == {"node": "play", "run_id": run_id}


async def test_a_global_action_has_no_run_and_lists_its_own_workflows(
    app_with: Callable[..., Awaitable[httpx.AsyncClient]],
):
    client = await app_with(gamedev(), other())
    mine = await submit(client)
    await submit(client, "other")

    response = await call(client, "sweep")

    assert response.status_code == 200, response.text
    assert response.json() == {"run_id": None, "runs": [mine]}


async def test_a_synchronous_handler_is_called_inline(
    app_with: Callable[..., Awaitable[httpx.AsyncClient]],
):
    client = await app_with(gamedev())

    response = await call(client, "plain")

    assert response.status_code == 200, response.text
    assert response.json() == {"sync": True}


async def test_an_action_with_no_model_ignores_whatever_was_sent(
    app_with: Callable[..., Awaitable[httpx.AsyncClient]],
):
    """An action with no form takes no value, and refusing one would be
    refusing a client that did nothing wrong."""

    client = await app_with(gamedev())

    response = await call(client, "sweep", payload={"anything": [1, 2, 3]})

    assert response.status_code == 200, response.text


async def test_the_body_defaults_to_an_empty_scope_and_no_input(
    app_with: Callable[..., Awaitable[httpx.AsyncClient]],
):
    client = await app_with(gamedev())

    response = await client.post("/api/plugins/gamedev/actions/sweep", json={})

    assert response.status_code == 200, response.text
    assert response.json()["run_id"] is None


# -- validation -------------------------------------------------------------


async def test_input_is_validated_against_the_action_model(
    app_with: Callable[..., Awaitable[httpx.AsyncClient]],
):
    """08 §Conventions' 422, with the `loc` paths of the *model*."""

    client = await app_with(gamedev())
    run_id = await submit(client)

    response = await call(
        client, "override", scope={"run_id": run_id}, payload={"reason": "no word"}
    )

    assert response.status_code == 422, response.text
    body = response.json()
    assert body["error"] == "validation failed"
    assert body["code"] == "validation"
    assert [error["loc"] for error in body["errors"]] == [["word"]]
    assert body["errors"][0]["type"] == "missing"


async def test_a_constraint_inside_the_model_is_validated_too(
    app_with: Callable[..., Awaitable[httpx.AsyncClient]],
):
    client = await app_with(gamedev())
    run_id = await submit(client)

    response = await call(
        client,
        "override",
        scope={"run_id": run_id},
        payload={"word": "crucible", "weight": 0},
    )

    assert response.status_code == 422
    assert [error["loc"] for error in response.json()["errors"]] == [["weight"]]


async def test_input_of_the_wrong_shape_entirely_is_a_422(
    app_with: Callable[..., Awaitable[httpx.AsyncClient]],
):
    client = await app_with(gamedev())
    run_id = await submit(client)

    response = await call(
        client, "override", scope={"run_id": run_id}, payload="a string"
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation"


async def test_a_malformed_scope_is_the_same_422(
    app_with: Callable[..., Awaitable[httpx.AsyncClient]],
):
    """The body's own shape is FastAPI's to check, and it answers the
    same way, because there is one 422 in this API."""

    client = await app_with(gamedev())

    response = await client.post(
        "/api/plugins/gamedev/actions/sweep",
        json={"scope": {"task_id": "not a number"}},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation"


async def test_nothing_runs_when_the_input_is_refused(
    app_with: Callable[..., Awaitable[httpx.AsyncClient]], store: Store
):
    """Validation is before the handler: a refused call writes nothing."""

    client = await app_with(gamedev())
    run_id = await submit(client)
    task_id = await first_task(store, run_id)

    response = await call(client, "note", scope={"task_id": task_id}, payload={})

    assert response.status_code == 422
    async with store.reader() as reader:
        assert await reader.log.list(run_id) == []


# -- scope and ownership ----------------------------------------------------


async def test_a_foreign_run_is_404_and_never_403(
    app_with: Callable[..., Awaitable[httpx.AsyncClient]],
):
    """Whether a run exists is not something one workflow's plugin
    learns about another's (09 §Context and scopes)."""

    client = await app_with(gamedev(), other())
    theirs = await submit(client, "other")

    response = await call(
        client, "override", scope={"run_id": theirs}, payload={"word": "crucible"}
    )

    assert response.status_code == 404
    assert response.json()["code"] == "plugin_error"
    assert "belongs to workflow 'other'" in response.json()["error"]


async def test_a_run_that_does_not_exist_is_404(
    app_with: Callable[..., Awaitable[httpx.AsyncClient]],
):
    client = await app_with(gamedev())

    response = await call(
        client,
        "override",
        scope={"run_id": "01JQNOTAREALRUNID0000000"},
        payload={"word": "crucible"},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "plugin_error"


async def test_a_task_of_another_run_is_404(
    app_with: Callable[..., Awaitable[httpx.AsyncClient]], store: Store
):
    client = await app_with(gamedev())
    first = await submit(client)
    second = await submit(client)

    response = await call(
        client,
        "note",
        scope={"run_id": first, "task_id": await first_task(store, second)},
        payload={"word": "a note"},
    )

    assert response.status_code == 404
    assert "does not belong to run" in response.json()["error"]


async def test_a_node_the_workflow_does_not_have_is_404(
    app_with: Callable[..., Awaitable[httpx.AsyncClient]],
):
    client = await app_with(gamedev())
    run_id = await submit(client)

    response = await call(client, "watch", scope={"run_id": run_id, "node": "nope"})

    assert response.status_code == 404
    assert "has no node 'nope'" in response.json()["error"]


@pytest.mark.parametrize(
    ("name", "scope", "payload", "refusal"),
    [
        ("override", {}, {"word": "crucible"}, NO_RUN),
        ("note", {}, {"word": "a note"}, NO_RUN),
        ("watch", {}, None, NO_RUN),
    ],
)
async def test_an_action_whose_scope_has_no_run_refuses_before_the_handler(
    app_with: Callable[..., Awaitable[httpx.AsyncClient]],
    name: str,
    scope: dict[str, Any],
    payload: Any,
    refusal: str,
):
    client = await app_with(gamedev())

    response = await call(client, name, scope=scope, payload=payload)

    assert response.status_code == 400
    assert response.json() == {"error": refusal, "code": "plugin_error"}


async def test_a_task_scoped_action_with_only_a_run_refuses_one_level_in(
    app_with: Callable[..., Awaitable[httpx.AsyncClient]],
):
    client = await app_with(gamedev())
    run_id = await submit(client)

    response = await call(
        client, "note", scope={"run_id": run_id}, payload={"word": "a note"}
    )

    assert response.status_code == 400
    assert response.json() == {"error": NO_TASK, "code": "plugin_error"}


async def test_a_node_scoped_action_with_no_node_refuses(
    app_with: Callable[..., Awaitable[httpx.AsyncClient]],
):
    """A run whose attempt was not named leaves no node in scope."""

    client = await app_with(gamedev())
    run_id = await submit(client)

    response = await call(client, "watch", scope={"run_id": run_id})

    assert response.status_code == 400
    assert response.json() == {"error": NO_NODE, "code": "plugin_error"}


async def test_a_global_action_is_never_refused_for_scope(
    app_with: Callable[..., Awaitable[httpx.AsyncClient]],
):
    client = await app_with(gamedev())

    assert (await call(client, "sweep")).status_code == 200


# -- what is not there ------------------------------------------------------


async def test_an_unregistered_workflow_is_404(
    app_with: Callable[..., Awaitable[httpx.AsyncClient]],
):
    client = await app_with(gamedev())

    response = await call(client, "override", workflow="nobody")

    assert response.status_code == 404
    assert response.json()["code"] == "plugin_error"
    assert "no workflow 'nobody'" in response.json()["error"]


async def test_an_action_the_workflow_does_not_declare_is_404(
    app_with: Callable[..., Awaitable[httpx.AsyncClient]],
):
    client = await app_with(gamedev())

    response = await call(client, "nope")

    assert response.status_code == 404
    assert "declares no action 'nope'" in response.json()["error"]


async def test_one_workflows_action_is_not_reachable_under_another(
    app_with: Callable[..., Awaitable[httpx.AsyncClient]],
):
    client = await app_with(gamedev(), other())

    response = await call(client, "peek", workflow="gamedev")

    assert response.status_code == 404


async def test_the_endpoint_exists_with_nothing_registered(
    app_with: Callable[..., Awaitable[httpx.AsyncClient]],
):
    """One endpoint for the process, not one per workflow: a server with
    no plugins still answers 404 rather than not routing at all."""

    client = await app_with()

    response = await call(client, "override")

    assert response.status_code == 404
    assert response.json()["code"] == "plugin_error"


# -- refusals ---------------------------------------------------------------


async def test_a_plugin_error_carries_its_own_status(
    app_with: Callable[..., Awaitable[httpx.AsyncClient]],
):
    client = await app_with(gamedev())

    response = await call(client, "refuse")

    assert response.status_code == 409
    assert response.json() == {
        "error": "the word has already been overridden",
        "code": "plugin_error",
    }


async def test_a_handler_that_raises_anything_else_is_a_500(
    app_with: Callable[..., Awaitable[httpx.AsyncClient]],
):
    """A defect is not a refusal: the API has no vocabulary for it and
    says so honestly rather than dressing it as a client error."""

    client = await app_with(gamedev())

    with pytest.raises(RuntimeError, match="the plugin is broken"):
        await call(client, "boom")


async def test_the_endpoint_is_in_the_document_under_the_plugins_tag(
    app_with: Callable[..., Awaitable[httpx.AsyncClient]],
):
    """A plugin's *routes* are not part of the committed wire contract,
    but the endpoint every action is invoked through is (08 §Plugins)."""

    client = await app_with()

    document = (await client.get("/openapi.json")).json()
    operation = document["paths"]["/api/plugins/{wf}/actions/{name}"]["post"]

    assert operation["tags"] == ["plugins"]
    assert operation["security"] == [{"operatorBearer": []}]
    assert "401" in operation["responses"]

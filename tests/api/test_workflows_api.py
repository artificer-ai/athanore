"""`/api/workflows`: what this server can run, its source, and submitting (T044).

The four things 17 §T044 asks of the router — the list shape including
generations and node options, a 404 for a name nothing is registered
under, a line per node from `/source`, and a submission that answers 201
with a `queued` run — plus the edges each of them has: an application
with no engine, a node whose body lives in another file, and a workflow
whose Python cannot be read at all.

The workflow under test is built in *this* module on purpose. `/source`
reports the file the start node's body was defined in, so the file it
reports is this one, and the line it gives for each node can be checked
against the text it returned rather than against a number written down
here.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from athanore.api.app import create_app
from athanore.engine import Engine
from athanore.engine.pools import Pool
from athanore.graph import Graph
from athanore.settings import AthanoreSettings
from athanore.store.rows import RunStatus
from athanore.store.uow import Store
from athanore.workflow import Workflow

#: This module's own file and text, read once at import. `/source` returns
#: both, and reading them inside an async test is a blocking call on the
#: event loop (ASYNC240).
THIS_FILE = Path(__file__).resolve()
SOURCE = THIS_FILE.read_text(encoding="utf-8")

# -- the workflow under test ------------------------------------------------

demo = Workflow("demo")


@demo.node(start=True, label="Plan the work", priority=5)
async def plan(build: Any) -> None:
    """Decide what to build."""


@demo.node(retries=2, timeout=30.0)
async def build(review: Any) -> None:
    """Do the work."""


@demo.node()
async def review() -> None:
    """Look at what was done."""


async def solo() -> None:
    """The one node of a one-node workflow."""


@pytest.fixture
def registered(engine: Engine) -> Graph:
    """`demo`, registered on a pool of two."""

    graph = demo.finalize()
    engine.register(graph, Pool("demo_pool", capacity=2))
    return graph


def anonymous_client(app: FastAPI) -> httpx.AsyncClient:
    """A client for an application this test built itself."""

    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    )


# -- the list ---------------------------------------------------------------


async def test_the_list_carries_the_graph_the_pool_and_the_node_options(
    client: httpx.AsyncClient, registered: Graph
) -> None:
    """08 §Workflows' row, field for field."""

    response = await client.get("/api/workflows")

    assert response.status_code == 200
    (body,) = response.json()
    assert body["name"] == "demo"
    assert body["start"] == "plan"
    assert body["pool"] == "demo_pool"
    assert body["capacity"] == 2
    assert body["in_flight"] == 0
    # The placeholder until the plugin registry lands (09, T049).
    assert body["plugin"] == {"panels": [], "actions": []}
    assert set(body["nodes"]) == {"plan", "build", "review"}


async def test_the_list_reports_generations_and_every_node_option(
    client: httpx.AsyncClient, registered: Graph
) -> None:
    """The BFS depth and the node metadata of 04 §Node options."""

    nodes = (await client.get("/api/workflows")).json()[0]["nodes"]

    assert [nodes[name]["generation"] for name in ("plan", "build", "review")] == [
        0,
        1,
        2,
    ]
    assert nodes["plan"] == {
        "edges": ["build"],
        "generation": 0,
        "priority": 5,
        "retries": None,
        "timeout": None,
        "label": "Plan the work",
        "description": "Decide what to build.",
    }
    assert nodes["build"]["retries"] == 2
    assert nodes["build"]["timeout"] == 30.0
    # An option nobody declared is null — "the server default" — rather
    # than a number this layer guessed at (01 §Real data only).
    assert nodes["review"]["priority"] is None
    # The label falls back to the function's name, the description to its
    # docstring.
    assert nodes["review"]["label"] == "review"
    assert nodes["review"]["description"] == "Look at what was done."


async def test_in_flight_is_the_pools_leased_slots(
    client: httpx.AsyncClient, engine: Engine, registered: Graph
) -> None:
    """Capacity is shared, so what is spoken for is the pool's count."""

    lease = engine.pools.get("demo_pool").try_acquire(task_id=1)
    assert lease is not None

    body = (await client.get("/api/workflows")).json()[0]
    assert body["capacity"] == 2
    assert body["in_flight"] == 1


async def test_the_list_is_ordered_by_name(
    client: httpx.AsyncClient, engine: Engine, registered: Graph
) -> None:
    """A stable order, so the SPA's chips do not reshuffle on a refresh."""

    other = Workflow("alpha")
    other.node(start=True)(solo)
    engine.register(other.finalize())

    body = (await client.get("/api/workflows")).json()

    assert [one["name"] for one in body] == ["alpha", "demo"]
    # A workflow registered without a pool joins the default one, sized
    # by `workers` (04 §Pools).
    assert body[0]["pool"] == "default"
    assert body[0]["capacity"] == 1


async def test_a_server_with_no_engine_runs_no_workflows(
    settings: AthanoreSettings,
) -> None:
    """`create_app()` without collaborators is the OpenAPI dump's app."""

    async with anonymous_client(create_app(settings=settings)) as http:
        listed = await http.get("/api/workflows")
        unknown = await http.get("/api/workflows/demo")

    assert listed.json() == []
    assert unknown.status_code == 404
    assert unknown.json()["code"] == "unknown_workflow"


# -- one workflow -----------------------------------------------------------


async def test_one_workflow_is_the_same_row(
    client: httpx.AsyncClient, registered: Graph
) -> None:
    listed = (await client.get("/api/workflows")).json()

    assert (await client.get("/api/workflows/demo")).json() == listed[0]


async def test_an_unknown_workflow_is_a_404(
    client: httpx.AsyncClient, registered: Graph
) -> None:
    """404 `unknown_workflow`, and the body names what is registered."""

    response = await client.get("/api/workflows/nope")

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "unknown_workflow"
    assert "demo" in body["error"]


# -- the source -------------------------------------------------------------


async def test_source_returns_the_module_and_a_line_per_node(
    client: httpx.AsyncClient, registered: Graph
) -> None:
    """The line each node's body starts on, checked against the text."""

    response = await client.get("/api/workflows/demo/source")

    assert response.status_code == 200
    body = response.json()
    assert Path(body["file"]) == THIS_FILE
    assert body["source"] == SOURCE

    lines = body["source"].splitlines()
    assert set(body["nodes"]) == {"plan", "build", "review"}
    for name in body["nodes"]:
        line = body["nodes"][name]["line"]
        # `getsourcelines` starts at the decorator, which is what the
        # library's source viewer marks.
        assert lines[line - 1].startswith("@demo.node")
        assert f"async def {name}(" in "\n".join(lines[line - 1 : line + 3])


async def test_source_leaves_out_a_node_defined_in_another_file(
    client: httpx.AsyncClient, engine: Engine, tmp_path: Path
) -> None:
    """A line into text that does not contain it is worse than no line.

    The second file is written and imported here rather than committed,
    so the case is unmistakably "another module" and nothing else in the
    suite depends on the arrangement.
    """

    elsewhere = _module(
        tmp_path / "elsewhere.py",
        'async def audit() -> None:\n    """A node body defined in another file."""\n',
    )
    mixed = Workflow("mixed")

    @mixed.node(start=True)
    async def open_(audit: Any) -> None:
        """The node this workflow's file is reported from."""

    mixed.node()(elsewhere.audit)
    engine.register(mixed.finalize())

    body = (await client.get("/api/workflows/mixed/source")).json()

    assert Path(body["file"]) == THIS_FILE
    assert set(body["nodes"]) == {"open_"}
    assert "audit" not in body["nodes"]


async def test_source_is_a_404_when_python_cannot_produce_it(
    client: httpx.AsyncClient, engine: Engine
) -> None:
    """A body built by `exec` has no file, so this view of it does not exist."""

    namespace: dict[str, Any] = {}
    exec("async def ghost() -> None:\n    ...\n", namespace)
    ghostly = Workflow("ghostly")
    ghostly.node(start=True)(namespace["ghost"])
    engine.register(ghostly.finalize())

    response = await client.get("/api/workflows/ghostly/source")

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


async def test_source_of_an_unknown_workflow_is_a_404(
    client: httpx.AsyncClient, registered: Graph
) -> None:
    response = await client.get("/api/workflows/nope/source")

    assert response.status_code == 404
    assert response.json()["code"] == "unknown_workflow"


def _module(path: Path, source: str) -> Any:
    """Write ``source`` to ``path`` and import it as a module.

    A real file on disk, because the point of the test that uses it is
    what :mod:`inspect` says about where a function was defined.
    """

    path.write_text(source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        del sys.modules[spec.name]
    return module


# -- submitting -------------------------------------------------------------


async def test_submitting_answers_201_with_a_queued_run(
    client: httpx.AsyncClient, store: Store, registered: Graph
) -> None:
    """The run and its start task, in one transaction (04 §Submit a run)."""

    response = await client.post(
        "/api/workflows/demo/runs",
        json={"title": "  ship it  ", "description": "the whole thing"},
    )

    assert response.status_code == 201
    run_id = response.json()["run_id"]

    async with store.reader() as reader:
        run = await reader.runs.get(run_id)
        tasks = await reader.tasks.list_for_run(run_id)
    assert run is not None
    assert run.status is RunStatus.queued
    assert run.title == "ship it"
    assert run.description == "the whole thing"
    (task,) = tasks
    assert task.node == "plan"
    assert task.payload == {"title": "ship it", "description": "the whole thing"}


async def test_a_description_is_optional(
    client: httpx.AsyncClient, store: Store, registered: Graph
) -> None:
    response = await client.post("/api/workflows/demo/runs", json={"title": "bare"})

    assert response.status_code == 201
    async with store.reader() as reader:
        run = await reader.runs.get(response.json()["run_id"])
    assert run is not None
    assert run.description == ""


@pytest.mark.parametrize("title", ["", "   ", None])
async def test_a_run_with_no_title_is_a_422(
    client: httpx.AsyncClient, registered: Graph, title: str | None
) -> None:
    """A run with no title is unfindable in every list that shows one."""

    response = await client.post("/api/workflows/demo/runs", json={"title": title})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation"
    assert body["errors"][0]["loc"] == ["body", "title"]


async def test_submitting_to_an_unknown_workflow_is_a_404(
    client: httpx.AsyncClient, registered: Graph
) -> None:
    response = await client.post("/api/workflows/nope/runs", json={"title": "x"})

    assert response.status_code == 404
    assert response.json()["code"] == "unknown_workflow"


async def test_submitting_without_an_engine_is_a_404(
    settings: AthanoreSettings,
) -> None:
    """Nothing is registered, so there is nothing to submit to."""

    async with anonymous_client(create_app(settings=settings)) as http:
        response = await http.post("/api/workflows/demo/runs", json={"title": "x"})

    assert response.status_code == 404
    assert response.json()["code"] == "unknown_workflow"


# -- the contract -----------------------------------------------------------


def test_every_route_is_tagged_for_the_generated_client(app: FastAPI) -> None:
    """08 §OpenAPI's tags group the generated client, so they are contract."""

    document = app.openapi()
    paths = sorted(
        path for path in document["paths"] if path.startswith("/api/workflows")
    )

    assert paths == [
        "/api/workflows",
        "/api/workflows/{name}",
        "/api/workflows/{name}/runs",
        "/api/workflows/{name}/source",
    ]
    for path in paths:
        for operation in document["paths"][path].values():
            assert operation["tags"] == ["workflows"]


async def test_the_operator_dependency_guards_every_route(
    tmp_path: Path, db_url: str
) -> None:
    """A network bind wants a bearer token on the workflow routes too."""

    settings = AthanoreSettings(
        root_path=tmp_path,
        db_url=db_url,
        host="0.0.0.0",
        operator_token=SecretStr("operator-token-9RTb"),
    )
    async with anonymous_client(create_app(settings=settings)) as http:
        refused = await http.get("/api/workflows")
        allowed = await http.get(
            "/api/workflows", headers={"Authorization": "Bearer operator-token-9RTb"}
        )

    assert refused.status_code == 401
    assert refused.json()["code"] == "unauthorized"
    assert allowed.status_code == 200

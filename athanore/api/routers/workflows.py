"""``/api/workflows``: what this server can run, and how to start it (08).

The first operator router, and the smallest. Everything it answers comes
from what is registered on the engine — the finalized graph, and the pool
that graph's tasks are dispatched on — so a workflow this server cannot
run is not listed, and asking for one by name is a 404 rather than an
entry with nothing behind it.

``/source`` is the exception: it answers from Python itself, through
:mod:`inspect`, because the workflow library overlay shows the *code* a
node runs (10 §Overlays, D35). Hot reload is a later seam; v1 requires a
restart, so the text this route returns is the text the running process
imported.

``POST /{name}/runs`` is the one write, and it does nothing itself:
:meth:`athanore.engine.ops.Ops.submit` inserts the run and its start
task in one transaction, emits the two events and wakes the scheduler
(04 §Submit a run). The router's whole job is to turn a body into
arguments and a row into a 201.
"""

from __future__ import annotations

import inspect
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi import Path as PathParam

from athanore.api.deps import operator_auth
from athanore.api.errors import ApiError, ErrorCode
from athanore.api.schemas import (
    Created,
    NewRun,
    SourceNode,
    SourceOut,
    WorkflowOut,
    WorkflowPlugin,
)
from athanore.engine import Engine, UnknownWorkflow
from athanore.graph import Graph
from athanore.plugins.registry import PluginSpec, manifest_entry

__all__ = ["router"]

router = APIRouter(
    prefix="/api/workflows",
    tags=["workflows"],
    dependencies=[Depends(operator_auth)],
)

#: The path parameter every route but the list takes.
WorkflowName = Annotated[str, PathParam(description="The registered workflow's name.")]


def _engine(request: Request) -> Engine | None:
    """The engine this application serves, if it was built with one.

    ``create_app()`` takes its collaborators rather than building them
    (04 §Shutdown), so an application without an engine is a real thing:
    the OpenAPI dump is one. It runs no workflows, which is what the
    routes below report — an empty list, and a 404 for any name.
    """

    engine: Engine | None = request.app.state.engine
    return engine


def _graphs(request: Request) -> dict[str, Graph]:
    """Every workflow registered on this server, by name."""

    engine = _engine(request)
    return dict(engine.graphs) if engine is not None else {}


def _graph(request: Request, name: str) -> Graph:
    """One registered workflow's finalized graph, or 404 ``unknown_workflow``."""

    graph = _graphs(request).get(name)
    if graph is None:
        raise UnknownWorkflow(
            f"workflow {name!r} is not registered; registered workflows are "
            f"{sorted(_graphs(request))}"
        )
    return graph


def _view(request: Request, graph: Graph) -> WorkflowOut:
    """``graph`` with the capacity of the pool it is bound to.

    ``in_flight`` is the pool's, not the workflow's: pools are shared, and
    what the operator needs to know is how much of the capacity this
    workflow's tasks compete for is spoken for (04 §Pools).
    """

    engine = _engine(request)
    if engine is None:  # pragma: no cover - `_graph` 404s without an engine
        raise UnknownWorkflow(f"workflow {graph.name!r} is not registered")
    pool = engine.pools.for_workflow(graph.name)
    counts = pool.snapshot()
    return WorkflowOut.of(
        graph,
        pool=pool.name,
        capacity=counts["capacity"],
        in_flight=counts["in_flight"],
        plugin=_plugin(request, graph.name),
    )


def _plugin(request: Request, name: str) -> WorkflowPlugin:
    """What this workflow contributes to the UI (08 §Workflows, 09).

    The same entries ``GET /api/plugins`` publishes, so the two views of
    one declaration cannot disagree: a workflow that declares nothing
    carries two empty lists, which is a fact rather than a placeholder.
    """

    specs: Sequence[PluginSpec] = getattr(request.app.state, "plugins", None) or ()
    spec = next((one for one in specs if one.workflow == name), None)
    if spec is None:
        return WorkflowPlugin()
    entry = manifest_entry(spec)
    return WorkflowPlugin(panels=entry["panels"], actions=entry["actions"])


@router.get("", summary="Every workflow this server can run")
async def list_workflows(request: Request) -> list[WorkflowOut]:
    """The registered workflows, by name.

    What the New Run overlay's workflow chips and the library's left list
    are built from (10 §Overlays). A server with nothing registered
    answers with an empty list: it runs no workflows, which is a fact
    rather than a failure.
    """

    return [_view(request, graph) for _, graph in sorted(_graphs(request).items())]


@router.get("/{name}", summary="One workflow")
async def get_workflow(request: Request, name: WorkflowName) -> WorkflowOut:
    """One registered workflow, or 404 `unknown_workflow`."""

    return _view(request, _graph(request, name))


@router.get("/{name}/source", summary="The Python a workflow is defined in")
async def get_source(request: Request, name: WorkflowName) -> SourceOut:
    """The module a workflow's nodes are defined in, and their line numbers.

    The file is the one the **start node's** body is defined in — the
    module the author wrote the workflow in — and ``nodes`` carries a line
    for each node whose body is defined in that same file. A node whose
    function was imported from elsewhere is left out rather than given a
    line into text that does not contain it (01 §Real data only).

    A workflow whose source Python cannot produce — a body built by
    ``exec``, or one whose file has been deleted since import — is a 404:
    the workflow is registered, but this view of it does not exist.
    """

    graph = _graph(request, name)
    file = _source_file(graph.start_node.fn)
    if file is None:
        raise ApiError(
            404,
            ErrorCode.not_found,
            f"no source is available for workflow {name!r}: its start node's "
            f"body was not defined in a file this process can read",
        )
    try:
        source = file.read_text(encoding="utf-8")
    except OSError as exc:
        raise ApiError(
            404,
            ErrorCode.not_found,
            f"the source of workflow {name!r} cannot be read: {exc}",
        ) from exc

    nodes: dict[str, SourceNode] = {}
    for node_name, node in graph.nodes.items():
        if _source_file(node.fn) != file:
            continue
        line = _source_line(node.fn)
        if line is not None:
            nodes[node_name] = SourceNode(line=line)
    return SourceOut(file=str(file), source=source, nodes=nodes)


@router.post(
    "/{name}/runs",
    status_code=status.HTTP_201_CREATED,
    summary="Submit a run",
)
async def submit_run(request: Request, name: WorkflowName, body: NewRun) -> Created:
    """Queue a run of this workflow, and return its id.

    The run is `queued` rather than `running`: waiting for a slot is a
    state an operator can see, and the first claim of one of its tasks is
    what flips it (03 §Run).
    """

    engine = _engine(request)
    if engine is None:
        raise UnknownWorkflow(
            f"workflow {name!r} is not registered; this server runs no workflows"
        )
    # An unregistered name is `Ops.submit`'s own refusal — the same
    # `UnknownWorkflow` the other routes raise, and a 404 either way.
    run = await engine.ops.submit(name, body.title, body.description)
    return Created(run_id=run.id)


def _source_file(fn: object) -> Path | None:
    """The resolved file ``fn`` was defined in, or ``None``.

    ``None`` for anything :mod:`inspect` cannot place — a built-in, a body
    made by ``exec``, a function whose module has no file. Resolved so
    that two nodes of one module compare equal whatever path each was
    imported under.
    """

    try:
        found = inspect.getsourcefile(fn)  # type: ignore[arg-type]
    except TypeError:
        return None
    if found is None:
        return None
    return Path(found).resolve()


def _source_line(fn: object) -> int | None:
    """The 1-based line ``fn``'s definition starts on, or ``None``.

    :func:`inspect.getsourcelines` returns the decorators too, so the line
    is where `@wf.node(...)` sits rather than where `def` does — which is
    what the library's source viewer should be marking.
    """

    try:
        _, line = inspect.getsourcelines(fn)  # type: ignore[arg-type]
    except (OSError, TypeError):
        return None
    return line

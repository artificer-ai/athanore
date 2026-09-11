"""``/api/workflows``: what this server can run, how to start it, and
how to change the set while it serves (08 §Workflows, 22 §Wire).

The first operator router. Everything it answers comes from what is
registered on the engine — the finalized graph, and the pool that
graph's tasks are dispatched on — so a workflow this server cannot run
is not listed, and asking for one by name is a 404 rather than an entry
with nothing behind it.

``/source`` is the exception: it answers from Python itself, through
:mod:`inspect`, because the workflow library overlay shows the *code* a
node runs (10 §Overlays, D35). The text it returns is the text the
running process now runs — after a reload, the reloaded text, because
the loader invalidates ``linecache`` (22 §Reloading a module).

``POST /{name}/runs`` does nothing itself: :meth:`athanore.engine.ops.
Ops.submit` inserts the run and its start task in one transaction,
emits the two events and wakes the scheduler (04 §Submit a run). The
router's whole job is to turn a body into arguments and a row into a
201.

``POST``, ``PUT /{name}`` and ``DELETE /{name}`` are the live
registrations of 22: add a workflow from a target, reload one under its
name, drop one. They reach the host through the registrar port
(:class:`~athanore.api.registrar.WorkflowRegistrar`) that ``create_app``
was handed — the API sits below the server and cannot name it — and an
application built without one answers them ``503``. What the port
raises is the loader's and the server's own vocabulary, and
:func:`_mapping_refusals` is the one place it becomes a status and a code:
a ``LoadError`` is the 422 whose body says where the load stopped, or
the 409 when it is the two conflicts 22 prices that way; an
``UnknownPool`` is 422; a pool move refused for attempts in flight is
409; a row that could not be written is 500. The mapping is here rather
than in :data:`athanore.api.errors.DOMAIN_ERRORS` because the
409-or-422 split on one exception type is a fact about these three
routes, and ``ValueError`` is too broad a type for a global row. The
traceback of a failed load is in the server log, never on the wire.
"""

from __future__ import annotations

import inspect
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Final

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi import Path as PathParam

from athanore.api.deps import operator_auth
from athanore.api.errors import ApiError, ErrorCode
from athanore.api.registrar import WorkflowRegistrar
from athanore.api.schemas import (
    Created,
    NewRun,
    RegisterWorkflow,
    ReloadWorkflow,
    RemovedWorkflowOut,
    SourceNode,
    SourceOut,
    WorkflowOut,
    WorkflowPlugin,
)
from athanore.engine import Engine, UnknownWorkflow
from athanore.graph import Graph
from athanore.plugins.discovery import LoadError, UnknownPool
from athanore.plugins.mount import MountedPlugins
from athanore.plugins.persist import PersistError
from athanore.plugins.registry import manifest_entry

__all__ = ["PERSISTED_HEADER", "router"]

#: The receipt a registration that wrote or removed a row of
#: ``athanore.toml`` carries: the file's path (22 §Wire). Absent from a
#: response that touched no file — ``persist`` not asked for, or a
#: ``DELETE ?persist=true`` of a name that had no row (D244).
PERSISTED_HEADER: Final = "X-Athanore-Persisted"

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


def _registrar(request: Request) -> WorkflowRegistrar | None:
    """The host's registrar, if the application was built with one."""

    registrar: WorkflowRegistrar | None = request.app.state.registrar
    return registrar


def _registering(request: Request) -> WorkflowRegistrar:
    """The registrar, or the 503 an application without one answers."""

    registrar = _registrar(request)
    if registrar is None:
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ErrorCode.registration_unavailable,
            "this application was built without a registrar; workflows cannot "
            "be registered over the API",
        )
    return registrar


def _view(request: Request, graph: Graph) -> WorkflowOut:
    """``graph`` with the capacity of the pool it is bound to.

    ``in_flight`` is the pool's, not the workflow's: pools are shared, and
    what the operator needs to know is how much of the capacity this
    workflow's tasks compete for is spoken for (04 §Pools). ``target`` is
    what the registrar recorded the workflow was loaded from — ``None``
    for a programmatic registration, and for every workflow of an
    application built without a registrar (22 §Terms).
    """

    engine = _engine(request)
    if engine is None:  # pragma: no cover - `_graph` 404s without an engine
        raise UnknownWorkflow(f"workflow {graph.name!r} is not registered")
    pool = engine.pools.for_workflow(graph.name)
    counts = pool.snapshot()
    registrar = _registrar(request)
    return WorkflowOut.of(
        graph,
        pool=pool.name,
        capacity=counts["capacity"],
        in_flight=counts["in_flight"],
        plugin=_plugin(request, graph.name),
        target=registrar.targets.get(graph.name) if registrar is not None else None,
    )


def _plugin(request: Request, name: str) -> WorkflowPlugin:
    """What this workflow contributes to the UI (08 §Workflows, 09).

    The same entries ``GET /api/plugins`` publishes, read off the live
    collection per request so the two views of one declaration cannot
    disagree (22 §Live mounting): a workflow that declares nothing
    carries two empty lists, which is a fact rather than a placeholder.
    """

    plugins: MountedPlugins = request.app.state.plugins
    spec = plugins.get(name)
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


# -- live registration (22 §Wire) ---------------------------------------------


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Register a workflow from a target",
)
async def register_workflow(
    request: Request, response: Response, body: RegisterWorkflow
) -> WorkflowOut:
    """Load `target` and register the workflow it names, without a restart.

    The name it registers under is the loaded workflow's own. Answers 201
    with the workflow as `GET /api/workflows/{name}` reports it; 409
    `conflict` if that name is already registered; 422
    `workflow_load_failed` when the load stopped — its body carries
    `target`, `stage` (`target`, `import`, `attribute`, `finalize`,
    `plugins` or `register`) and `detail`, the underlying error's full
    message; 422 `unknown_pool` for a `pool` the engine does not have,
    naming the ones it does; 500 `persist_failed` (`path`, `detail`) when
    `persist` was asked for and the row could not be written, in which
    case nothing was registered; 503 `registration_unavailable` from an
    application built without a registrar. A response that wrote the row
    carries `X-Athanore-Persisted: <path>`.
    """

    registrar = _registering(request)
    with _mapping_refusals():
        registered = await registrar.add_target(
            body.target, body.pool, persist=body.persist
        )
    _receipt(response, registered.persisted)
    return _view(request, _graph(request, registered.name))


@router.put("/{name}", summary="Reload a registered workflow")
async def reload_workflow(
    request: Request, response: Response, name: WorkflowName, body: ReloadWorkflow
) -> WorkflowOut:
    """Load `target` — or the registration's recorded one — and replace `name`.

    The next task of every run of the workflow dispatches on the new
    graph; an attempt already running finishes on the body it started
    with. Answers 200 with the workflow as `GET /api/workflows/{name}`
    now reports it; 404 `unknown_workflow`; 409 `conflict` if the target
    now defines a differently named workflow (that is a new workflow —
    `POST` it) or `pool` would move the workflow while attempts of it are
    in flight; 422 `workflow_load_failed` as `POST` answers, with `stage:
    "target"` when `target` was omitted and the registration has no
    recorded one; 422 `unknown_pool`; 500 `persist_failed`; 503
    `registration_unavailable`. A response that rewrote the row carries
    `X-Athanore-Persisted: <path>`.
    """

    _graph(request, name)
    registrar = _registering(request)
    with _mapping_refusals():
        registered = await registrar.reload_target(
            name, body.target, body.pool, persist=body.persist
        )
    _receipt(response, registered.persisted)
    return _view(request, _graph(request, registered.name))


@router.delete("/{name}", summary="Unregister a workflow")
async def remove_workflow(
    request: Request,
    response: Response,
    name: WorkflowName,
    persist: Annotated[
        bool,
        Query(
            description="Remove the `[workflows.<name>]` row of `athanore.toml` "
            "too; a name with no row is not an error."
        ),
    ] = False,
) -> RemovedWorkflowOut:
    """Drop the workflow `name`, interrupting whatever it was running.

    Every attempt of it in flight is cancelled and left where it was — no
    task status is written, and the run reads `unregistered: true` until
    the workflow is registered again, at which point those rows are
    recovered. Nothing is deleted. Answers 200 with the interrupted task
    ids; 404 `unknown_workflow`; 500 `persist_failed`; 503
    `registration_unavailable`. A response that removed the row carries
    `X-Athanore-Persisted: <path>`; one that found no row to remove
    carries no such header.
    """

    _graph(request, name)
    registrar = _registering(request)
    with _mapping_refusals():
        removed = await registrar.remove(name, persist=persist)
    _receipt(response, removed.persisted)
    return RemovedWorkflowOut(
        workflow=removed.workflow, task_ids=list(removed.task_ids)
    )


def _receipt(response: Response, persisted: Path | None) -> None:
    """Put the path a verb wrote or removed a row of on the response."""

    if persisted is not None:
        response.headers[PERSISTED_HEADER] = str(persisted)


@contextmanager
def _mapping_refusals() -> Iterator[None]:
    """The registrar's refusals as the statuses and codes of 22 §Wire.

    One place, so the three routes price the same refusal the same way:

    - a ``LoadError`` with ``conflict`` set — a ``POST`` of a registered
      name, a ``PUT`` whose target now names another workflow — is
      **409** ``conflict``;
    - any other ``LoadError`` is **422** ``workflow_load_failed`` with
      exactly the body 22 §Wire gives: ``target``, ``stage``, ``detail``;
    - an ``UnknownPool`` is **422** ``unknown_pool``, the message naming
      the known pools;
    - a ``ValueError`` is the pool-move refusal of 22 §Pools, from the
      server's pre-check or the engine's own, and is **409** ``conflict``
      (``persist`` without a target, the other ``ValueError`` the verbs
      raise, cannot reach here — every port call carries one);
    - a ``PersistError`` is **500** ``persist_failed`` with ``path`` and
      ``detail``; the row is written before anything is mutated, so the
      message says the registration was not changed.
    """

    try:
        yield
    except LoadError as exc:
        if exc.conflict:
            raise ApiError(
                status.HTTP_409_CONFLICT, ErrorCode.conflict, exc.message
            ) from exc
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ErrorCode.workflow_load_failed,
            exc.message,
            target=exc.target,
            stage=exc.stage,
            detail=exc.detail,
        ) from exc
    except UnknownPool as exc:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorCode.unknown_pool, str(exc)
        ) from exc
    except ValueError as exc:
        raise ApiError(status.HTTP_409_CONFLICT, ErrorCode.conflict, str(exc)) from exc
    except PersistError as exc:
        raise ApiError(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            ErrorCode.persist_failed,
            f"{exc.path} was not updated and the registration was not changed: "
            f"{exc.detail}",
            path=str(exc.path),
            detail=exc.detail,
        ) from exc


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

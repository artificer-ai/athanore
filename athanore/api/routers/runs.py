"""``/api/runs``: every operator verb on a run, and the graph the SPA draws.

The biggest of the operator routers, and the one that does the least
thinking. Ten of its fourteen routes are one line of work each: turn a
path parameter and a body into arguments, hand them to
:class:`~athanore.engine.ops.Ops`, and turn what comes back into the
model 08 §Runs names. Every precondition — a run that is not paused, a
title that is blank, a join that has no arrivals to replay — belongs to
the engine, which raises the exception :mod:`athanore.api.errors` maps
onto a status code. Nothing is re-checked here, because a second copy of
a precondition is a second place for it to be wrong.

The four reads are where the work is.

- ``GET /{id}`` is 08's ``RunDetail``. ``RunRepo.detail`` answers with
  the run row, its attempts and their summed stats, and the two derived
  fields the list query computes in SQL are recomputed here from what
  that read already returned: ``current_nodes`` from the attempts that
  are ``in_progress`` or ``waiting``, and ``pending_requests`` from the
  run's pending request views. ``outputs`` is one entry per terminal
  attempt (D58) and ``output`` is the run's stored value, which the
  runner already shaped by 04 §Routing edge cases.
- ``GET /{id}/events`` pages the run's stored events into the typed
  envelope of 18, so the SPA gets the same object from history that it
  gets from the SSE feed.
- ``GET /{id}/graph`` is the workflow's shape with this run's history
  projected onto it, and :func:`graph_view` is that projection.
- ``GET /{id}/log`` and ``GET /{id}/requests`` are the run's work log and
  its requests, whole: the log is bounded by the number of stages
  (08 §Agent-facing) and a run's requests are bounded by what a person
  answered, so neither is paged.

``state`` is the part of the graph worth reading twice. A node in a run
has one state per attempt and two of them can be true at once — an
attempt that failed and a retry that is queued are both facts about the
same node — so 08 §Graph semantics fixes a precedence and
:data:`STATE_PRECEDENCE` is that list, read off
:class:`~athanore.api.schemas.graph.NodeState`'s member order rather than
restated. A node whose last attempt failed and whose retry is waiting for
a slot reports ``ready``, and that is the whole of the rule.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Annotated, Final

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi import Path as PathParam
from pydantic import TypeAdapter

from athanore.api.deps import operator_auth
from athanore.api.schemas import (
    Arrivals,
    EdgeKind,
    EditRun,
    EventEnvelope,
    GraphBranch,
    GraphEdge,
    GraphNode,
    GraphOut,
    LogEntry,
    LogRef,
    LogText,
    NodeState,
    Ok,
    Position,
    PositionOut,
    RequestView,
    Rerun,
    RunDetail,
    RunSummary,
    TaskRef,
)
from athanore.engine import Engine
from athanore.engine.errors import NotFound, UnknownWorkflow
from athanore.events.names import EventName
from athanore.graph import Graph, Node
from athanore.store import rows
from athanore.store.repos.joins import IncompleteJoin
from athanore.store.uow import Reader, Store

__all__ = ["router"]

router = APIRouter(
    prefix="/api/runs",
    tags=["runs"],
    dependencies=[Depends(operator_auth)],
)

#: The path parameter every route but the list takes.
RunId = Annotated[str, PathParam(description="The run id, a ULID.")]

#: The attempt statuses that put a node — and its run — "in" that node
#: right now. The same pair ``RunRepo.list`` aggregates ``current_nodes``
#: from, so the list and the detail cannot disagree about them.
IN_FLIGHT: Final = frozenset({rows.TaskStatus.in_progress, rows.TaskStatus.waiting})

#: 08 §Graph semantics' precedence, highest first, paired with the task
#: status each member is derived from. Every member of :class:`NodeState`
#: but ``idle`` is the name of a task status, so the order is read off
#: that enum's declaration rather than written out a second time here.
STATE_PRECEDENCE: Final[tuple[tuple[NodeState, rows.TaskStatus], ...]] = tuple(
    (state, rows.TaskStatus(state.value))
    for state in NodeState
    if state is not NodeState.idle
)

#: The states that make a node ``live`` on their own; a node with at
#: least one ``done`` attempt is live too (09 §Slots).
LIVE_STATES: Final = frozenset({NodeState.in_progress, NodeState.waiting})

#: The ``lineage.reason`` of a task enqueued by a transition, and the two
#: keys of the ``task.enqueued`` payload the traversal counts read.
TRANSITION_REASON: Final = "transition"

#: How many events one page of the traversal scan reads. The scan
#: accumulates counts rather than rows, so paging it keeps ``/graph``'s
#: memory flat on a run with a long history while still counting every
#: edge crossing — a capped single read would undercount silently.
EVENT_PAGE: Final = 1000

#: The default and the maximum of ``?limit=`` on ``/{id}/events``. The
#: maximum is the default ``sse_replay_cap`` of 08 §Events, so one page
#: of history is never larger than one SSE replay.
DEFAULT_EVENT_LIMIT: Final = 500
MAX_EVENT_LIMIT: Final = 5000

#: One stored event as the typed envelope of 18. Built once: a
#: ``TypeAdapter`` compiles its validator on construction.
_ENVELOPE: Final[TypeAdapter[EventEnvelope]] = TypeAdapter(EventEnvelope)


# --------------------------------------------------------------------------
# The collaborators, and what their absence means
# --------------------------------------------------------------------------


def _engine(request: Request) -> Engine | None:
    """The engine this application serves, if it was built with one.

    ``create_app()`` takes its collaborators rather than building them,
    so an application without an engine is a real thing: the OpenAPI
    dump is one (04 §Shutdown).
    """

    engine: Engine | None = request.app.state.engine
    return engine


def _store(request: Request) -> Store | None:
    """The store this application reads runs from, if it has one."""

    store: Store | None = request.app.state.store
    return store


def _reader_store(request: Request, run_id: str) -> Store:
    """The store, or the 404 a run lookup gets without one.

    An application with no store holds no runs, so the honest answer to
    "give me this run" is that it does not exist — not a 500 about the
    server's own wiring.
    """

    store = _store(request)
    if store is None:
        raise NotFound(f"run {run_id!r} does not exist: this server has no store")
    return store


def _engine_for(request: Request, run_id: str) -> Engine:
    """The engine an operator verb needs, or the same 404."""

    engine = _engine(request)
    if engine is None:
        raise NotFound(f"run {run_id!r} does not exist: this server runs no workflows")
    return engine


def _graphs(request: Request) -> Mapping[str, Graph]:
    """Every workflow registered on this server, by name."""

    engine = _engine(request)
    return engine.graphs if engine is not None else {}


async def _run(reader: Reader, run_id: str) -> rows.RunRow:
    """The run, or 404 ``not_found``."""

    run = await reader.runs.get(run_id)
    if run is None:
        raise NotFound(f"run {run_id!r} does not exist")
    return run


# --------------------------------------------------------------------------
# The run list and the run detail
# --------------------------------------------------------------------------


def _summary(row: rows.RunSummary, registered: Mapping[str, Graph]) -> RunSummary:
    """One list row, with ``unregistered`` filled in from the registry.

    The column does not exist: whether *this* server can run the
    workflow is the registry's question, and the store has no opinion
    (03 §Run).
    """

    view = RunSummary.of(row)
    view.unregistered = row.workflow not in registered
    return view


@router.get("", summary="Every run, in dispatch order")
async def list_runs(
    request: Request,
    status_: Annotated[
        rows.RunStatus | None,
        Query(alias="status", description="Only runs in this status."),
    ] = None,
    workflow: Annotated[
        str | None, Query(description="Only runs of this workflow.")
    ] = None,
) -> list[RunSummary]:
    """The run list of 08 §Runs, whole.

    Run lists are small and return whole (08 §Conventions). The order is
    the dispatch order — ``position`` ascending — so the list the
    operator reads is the order the scheduler will claim in.

    An application with no store has no runs and answers with an empty
    list: "nothing to ask" and "nothing queued" are the same fact for a
    server that holds no work, unlike ``/api/health``'s counts.
    """

    store = _store(request)
    if store is None:
        return []
    async with store.reader() as reader:
        summaries = await reader.runs.list(
            None if status_ is None else status_.value, workflow
        )
    registered = _graphs(request)
    return [_summary(row, registered) for row in summaries]


@router.get("/{run_id}", summary="One run, its attempts and its totals")
async def get_run(request: Request, run_id: RunId) -> RunDetail:
    """A run with everything the overview pane draws (08 §Runs).

    ``current_nodes`` and ``pending_requests`` are the list query's two
    derived fields, recomputed from this read: the attempts are already
    in hand, so the in-flight nodes cost nothing, and the pending
    requests are one indexed query over this run alone.
    """

    store = _reader_store(request, run_id)
    async with store.reader() as reader:
        detail = await reader.runs.detail(run_id)
        if detail is None:
            raise NotFound(f"run {run_id!r} does not exist")
        run, tasks, stats = detail
        pending = await reader.requests.list_views(run_id, pending_only=True)
    summary = rows.RunSummary(
        **run.model_dump(),
        current_nodes=sorted({task.node for task in tasks if task.status in IN_FLIGHT}),
        pending_requests=len(pending),
        unregistered=run.workflow not in _graphs(request),
    )
    return RunDetail.of_run(summary, tasks=tasks, stats=stats)


@router.patch("/{run_id}", summary="Change a run's title or description")
async def edit_run(request: Request, run_id: RunId, body: EditRun) -> RunDetail:
    """Write the fields the body names, and answer with the run.

    A field the body omits is left alone, which is why an edit that
    names neither is accepted and changes nothing (``Ops.edit``). The
    response is the whole detail rather than the edited row: the SPA
    re-renders the overview from it, and a second GET to get the
    attempts back would be a round trip for nothing.
    """

    engine = _engine_for(request, run_id)
    await engine.ops.edit(run_id, title=body.title, description=body.description)
    return await get_run(request, run_id)


@router.delete(
    "/{run_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete a run and everything under it",
)
async def delete_run(request: Request, run_id: RunId) -> None:
    """Cancel what is outstanding, then remove the run.

    Both halves are ``Ops.delete``'s, in that order and for its reason:
    the attempts are killed against rows that still exist.
    """

    engine = _engine_for(request, run_id)
    await engine.ops.delete(run_id)


# --------------------------------------------------------------------------
# The verbs
# --------------------------------------------------------------------------


@router.post("/{run_id}/pause", summary="Stop a run dispatching")
async def pause_run(request: Request, run_id: RunId) -> Ok:
    """Pause a `queued` or `running` run; 409 on anything else.

    Pause is about the **next** task: an attempt already in flight runs
    to its end and enqueues its successor, and that successor waits (04
    §Operator operations). Killing running work is ``/cancel``.
    """

    engine = _engine_for(request, run_id)
    await engine.ops.pause(run_id)
    return Ok()


@router.post("/{run_id}/resume", summary="Let a paused run dispatch again")
async def resume_run(request: Request, run_id: RunId) -> Ok:
    """Resume a `paused` run; 409 on anything else."""

    engine = _engine_for(request, run_id)
    await engine.ops.resume(run_id)
    return Ok()


@router.post("/{run_id}/cancel", summary="End a run and everything under it")
async def cancel_run(request: Request, run_id: RunId) -> Ok:
    """Cancel the run and every outstanding attempt; 409 if it has ended.

    The ``note`` names how many attempts were stopped, because that is
    the part of the outcome the request could not predict: a run with
    nothing in flight and a run with three agents mid-turn are the same
    call and very different events. It is omitted when there were none,
    rather than sent as "0 attempts".
    """

    engine = _engine_for(request, run_id)
    cancelled = await engine.ops.cancel(run_id)
    if not cancelled:
        return Ok()
    plural = "" if len(cancelled) == 1 else "s"
    return Ok(note=f"{len(cancelled)} attempt{plural} cancelled")


@router.post("/{run_id}/rerun", summary="Run a node again")
async def rerun_node(request: Request, run_id: RunId, body: Rerun) -> TaskRef:
    """Enqueue a fresh attempt of ``node`` with the payload it last had.

    A join replays the arrivals the store holds rather than the payload
    its task was given, which is what makes a rerun the remedy for a
    branch that arrived late (04 §Failure and operator semantics).
    """

    engine = _engine_for(request, run_id)
    task = await engine.ops.rerun(run_id, body.node)
    return TaskRef(task_id=task.id)


@router.post("/{run_id}/position", summary="Move a run in the dispatch list")
async def move_run(request: Request, run_id: RunId, body: Position) -> PositionOut:
    """Swap with a neighbour, or move to a zero-based index (D57).

    Both ends are a no-op that still answers 200 with the position the
    run already had, and an ``index`` outside the list is clamped to it:
    "top" is `{"index": 0}` and there is nothing for the caller to
    bounds-check. The body model has already refused neither-or-both of
    the two fields.
    """

    engine = _engine_for(request, run_id)
    position = await engine.ops.reorder(
        run_id, direction=body.direction, index=body.index
    )
    return PositionOut(position=position)


@router.post("/{run_id}/log", summary="Append an operator note to the work log")
async def append_log(request: Request, run_id: RunId, body: LogText) -> LogRef:
    """Write a `user` entry under the run's current node.

    The node is the one node with an attempt in flight, and ``user``
    when there is not exactly one: a note filed under one branch of a
    fan-out would claim a context it does not have (``Ops.append_log``).
    """

    engine = _engine_for(request, run_id)
    entry = await engine.ops.append_log(run_id, body.text)
    return LogRef(log_id=entry.id)


# --------------------------------------------------------------------------
# The reads
# --------------------------------------------------------------------------


@router.get("/{run_id}/log", summary="A run's work log")
async def get_log(request: Request, run_id: RunId) -> list[LogEntry]:
    """Every entry of the work log, oldest first and never truncated.

    Whole, and unpaged: the log is bounded by the number of stages
    rather than by agent output (08 §Agent-facing). The `stats` entries
    an agent never sees are here — token counts are operator
    information.
    """

    store = _reader_store(request, run_id)
    async with store.reader() as reader:
        await _run(reader, run_id)
        entries = await reader.log.list(run_id)
    return [LogEntry.of(entry) for entry in entries]


@router.get("/{run_id}/events", summary="A run's stored events")
async def get_events(
    request: Request,
    run_id: RunId,
    after: Annotated[
        int, Query(ge=0, description="Return events after this event id.")
    ] = 0,
    limit: Annotated[
        int, Query(ge=1, le=MAX_EVENT_LIMIT, description="How many events to return.")
    ] = DEFAULT_EVENT_LIMIT,
) -> list[EventEnvelope]:
    """One page of the run's history, oldest first.

    The same typed envelope the SSE feed sends (18 §Typing), so a client
    that caught up from here and then subscribed switches sources
    without switching shapes. `task.stream` is ephemeral and is never
    stored, so it never appears in a page.
    """

    store = _reader_store(request, run_id)
    async with store.reader() as reader:
        await _run(reader, run_id)
        stored = await reader.events.list_for_run(run_id, after=after, limit=limit)
    return [_envelope(event) for event in stored]


@router.get("/{run_id}/requests", summary="A run's requests")
async def get_requests(request: Request, run_id: RunId) -> list[RequestView]:
    """Every request the run opened, answered or not, oldest first.

    The run's history rather than the inbox: a stale request — one whose
    attempt is gone — stays here and leaves ``/api/requests?pending=true``
    (06 §Restart durability).
    """

    store = _reader_store(request, run_id)
    async with store.reader() as reader:
        await _run(reader, run_id)
        views = await reader.requests.list_views(run_id)
    return [RequestView.of(view) for view in views]


@router.get("/{run_id}/graph", summary="The workflow's graph, for this run")
async def get_graph(request: Request, run_id: RunId) -> GraphOut:
    """The registered graph with this run's history projected onto it.

    A run whose workflow this server does not have registered is a 404
    ``unknown_workflow``: there is no graph to project onto, and the run
    list already says so with ``unregistered`` rather than pretending a
    shape.
    """

    store = _reader_store(request, run_id)
    async with store.reader() as reader:
        run = await _run(reader, run_id)
        graph = _graphs(request).get(run.workflow)
        if graph is None:
            raise UnknownWorkflow(
                f"run {run_id!r} runs workflow {run.workflow!r}, which is not "
                f"registered on this server, so it has no graph"
            )
        tasks = await reader.tasks.list_for_run(run_id)
        pending = await reader.joins.incomplete(run_id)
        node_of_task = {task.id: task.node for task in tasks}
        traversed = await _traversals(reader, run_id, node_of_task)
    return graph_view(graph, tasks, traversed=traversed, pending_joins=pending)


# --------------------------------------------------------------------------
# The graph projection (08 §Graph semantics)
# --------------------------------------------------------------------------


async def _traversals(
    reader: Reader, run_id: str, node_of_task: Mapping[int, str]
) -> dict[tuple[str, str], int]:
    """How often this run crossed each edge, by ``(from, to)``.

    Two event names carry a crossing and 08 §Graph semantics names both:
    ``task.enqueued`` with ``reason=transition``, whose ``from_task``
    names the attempt that routed and whose ``node`` is where it routed
    to; and ``join.arrived``, which is how a branch crosses into a join —
    a transition into a join enqueues nothing until the last branch
    lands, so counting only the first would leave every join edge
    reading zero until it fired.

    Paged, and counted as it pages: a run's history is unbounded, and a
    single capped read would silently undercount instead.
    """

    counts: dict[tuple[str, str], int] = {}
    patterns = [EventName.task_enqueued.value, EventName.join_arrived.value]
    after = 0
    while True:
        page = await reader.events.list_after(
            after=after, limit=EVENT_PAGE, run_id=run_id, patterns=patterns
        )
        for event in page:
            edge = _crossing(event, node_of_task)
            if edge is not None:
                counts[edge] = counts.get(edge, 0) + 1
        if len(page) < EVENT_PAGE:
            return counts
        after = page[-1].id


def _crossing(
    event: rows.EventRow, node_of_task: Mapping[int, str]
) -> tuple[str, str] | None:
    """The edge ``event`` crossed, or ``None`` if it crossed none.

    ``None`` for an enqueue that was not a transition — a start, a
    rerun, a retry, a move and a join dispatch all create a task without
    taking an edge — and for either event when the attempt it came from
    is not one of this run's, which cannot happen and is not worth a
    crash if it ever does.
    """

    if event.name == EventName.join_arrived.value:
        source = node_of_task.get(event.task_id) if event.task_id else None
        target = event.data.get("join")
        if source is None or not isinstance(target, str):
            return None
        return source, target
    if event.name != EventName.task_enqueued.value:
        return None
    if event.data.get("reason") != TRANSITION_REASON:
        return None
    from_task = event.data.get("from_task")
    target = event.data.get("node")
    if not isinstance(from_task, int) or not isinstance(target, str):
        return None
    source = node_of_task.get(from_task)
    return None if source is None else (source, target)


def _state(statuses: frozenset[rows.TaskStatus]) -> NodeState:
    """What a node with these attempt statuses is doing, by 08's precedence.

    First match wins, which is what makes a failed attempt with a retry
    queued report ``ready``: the retry row exists and the node is going
    to run again, so that is what the operator should see.
    """

    for state, status_ in STATE_PRECEDENCE:
        if status_ in statuses:
            return state
    return NodeState.idle


def _branches(node_tasks: Sequence[rows.TaskRow]) -> list[GraphBranch]:
    """The node's attempts grouped by the branch they ran in.

    The branch is the whole frame stack: two branches of one fan-out
    differ in their innermost frame's ``index``, and a branch nested
    inside another is a different branch again. ``from_task`` is the
    fan-out that produced the branch — the innermost frame's ``fanout``,
    which is the ``lineage.from`` of the first task in the branch chain —
    and ``null`` for a node reached by a single path, which has exactly
    one branch.

    ``node_tasks`` arrives oldest first, so the groups come out in the
    order their first attempt was enqueued, which is branch order.
    """

    grouped: dict[tuple[tuple[int, int], ...], GraphBranch] = {}
    for task in node_tasks:
        key = tuple((frame.fanout, frame.index) for frame in task.branch)
        branch = grouped.get(key)
        if branch is None:
            branch = GraphBranch(
                from_task=task.branch[-1].fanout if task.branch else None, tasks=[]
            )
            grouped[key] = branch
        branch.tasks.append(task.id)
    return list(grouped.values())


def _arrivals(
    node: str, pending_joins: Iterable[IncompleteJoin], depth: Mapping[int, int]
) -> Arrivals | None:
    """How much of the innermost open fan-out has reached this join.

    ``None`` unless a fan-out into this node is still open. "Innermost"
    is the fan-out task nested deepest — the length of its own branch
    stack — and the most recent of those on a tie, which is the one the
    operator is waiting on (10 §Graph pane's `2 of 3 arrived`).
    """

    open_here = [join for join in pending_joins if join.join_node == node]
    if not open_here:
        return None
    innermost = max(
        open_here, key=lambda join: (depth.get(join.fanout_task, 0), join.fanout_task)
    )
    return Arrivals(arrived=innermost.arrived, count=innermost.count)


def graph_view(
    graph: Graph,
    tasks: Sequence[rows.TaskRow],
    *,
    traversed: Mapping[tuple[str, str], int],
    pending_joins: Sequence[IncompleteJoin],
) -> GraphOut:
    """The response of ``GET /api/runs/{id}/graph`` (08 §Graph semantics).

    Pure, and separate from the route, because everything it needs was
    already read: the graph the run's workflow finalized to, the run's
    attempts, the edge crossings counted off the event log, and the
    fan-outs that have not completed. Nodes come out in generation
    order and, within a generation, in the order the workflow declared
    them — the order the SPA's canvas ranks and spreads a rank in
    (10 §Graph pane).
    """

    by_node: dict[str, list[rows.TaskRow]] = {name: [] for name in graph.nodes}
    for task in tasks:
        # A task of a node the graph no longer has — a workflow edited
        # under a live run — belongs to no row here rather than to a
        # node invented for it.
        if task.node in by_node:
            by_node[task.node].append(task)
    depth = {task.id: len(task.branch) for task in tasks}
    declared = {name: index for index, name in enumerate(graph.nodes)}

    nodes: list[GraphNode] = []
    for name, node in sorted(
        graph.nodes.items(), key=lambda item: (item[1].generation, declared[item[0]])
    ):
        attempts = by_node[name]
        statuses = frozenset(task.status for task in attempts)
        state = _state(statuses)
        nodes.append(
            GraphNode(
                name=name,
                generation=node.generation,
                join=node.join,
                state=state,
                live=state in LIVE_STATES or rows.TaskStatus.done in statuses,
                attempts=len(attempts),
                last_task_id=max((task.id for task in attempts), default=None),
                branches=_branches(attempts),
                arrivals=(_arrivals(name, pending_joins, depth) if node.join else None),
            )
        )

    edges: list[GraphEdge] = []
    for name, node in graph.nodes.items():
        for target in node.edges:
            edges.append(
                GraphEdge(
                    from_=name,
                    to=target,
                    kind=_edge_kind(node.generation, graph.nodes[target]),
                    traversed=traversed.get((name, target), 0),
                )
            )
    return GraphOut(nodes=nodes, edges=edges)


def _edge_kind(generation: int, target: Node) -> EdgeKind:
    """Whether an arrow is a loop back, an arrow into a join, or a step.

    In 08 §Graph semantics' order: ``back`` first, because an arrow to a
    generation at or below its source is a loop however the target is
    declared, then ``join``, then ``forward``.
    """

    if target.generation <= generation:
        return EdgeKind.back
    return EdgeKind.join if target.join else EdgeKind.forward


def _envelope(event: rows.EventRow) -> EventEnvelope:
    """One stored row as the typed envelope of 18.

    Validated rather than hand-built: ``data``'s shape is fixed per
    event name, and the union is what OpenAPI publishes, so a row the
    vocabulary cannot type is a defect that should surface rather than
    reach the SPA as an object with the wrong fields.
    """

    return _ENVELOPE.validate_python(
        {
            "id": event.id,
            "run_id": event.run_id,
            "task_id": event.task_id,
            "name": event.name,
            "data": event.data,
            "created": event.created,
        }
    )

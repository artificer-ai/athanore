"""``/api/tasks``: one attempt, its transcript, and the three verbs on it (08).

The operator's view of a task, and only the operator's: everything an
agent may call lives under ``/api/agent/`` on its own router with its own
auth dependency and its own models (08 §Agent-facing, D39). The split is
what keeps :class:`~athanore.api.schemas.tasks.TaskDetail` free of a
token to omit — it has no field for one — rather than choosing a response
shape by credential the way the MVP did.

Four of the five routes are one line of work each. ``retry``, ``move``
and ``status`` hand their arguments to
:class:`~athanore.engine.ops.Ops` and turn the row that comes back into
08's acknowledgement; every precondition is the engine's, including the
one 17 §T044b names — a task moved into a **join** is a
:class:`~athanore.engine.errors.Conflict`, which
:mod:`athanore.api.errors` renders as 409 ``conflict``. Nothing is
re-checked here.

``/stream`` is the one route with a decision in it. It pages a task's
transcript by the ``seq`` cursor of 07 §Transcript writes, reports
``last_seq`` as the highest sequence **stored** rather than the highest
in the page — so a client that has caught up can tell — and reports
``live`` for an attempt that is still ``in_progress`` **or** ``waiting``.
A waiting attempt is parked on a request its operator has not answered
yet, and answering it is what makes the agent go on writing (10 §Panes'
docked request panel sits under that very stream), so a ``live`` that
excluded ``waiting`` would stop the SPA polling at the exact moment the
transcript is about to grow again.
"""

from __future__ import annotations

from typing import Annotated, Final

from fastapi import APIRouter, Depends, Query, Request
from fastapi import Path as PathParam

from athanore.api.deps import operator_auth
from athanore.api.schemas import (
    Move,
    Ok,
    SetStatus,
    StreamChunk,
    StreamOut,
    TaskDetail,
    TaskRef,
)
from athanore.engine import Engine
from athanore.engine.errors import NotFound
from athanore.store import rows
from athanore.store.uow import Reader, Store

__all__ = ["router"]

router = APIRouter(
    prefix="/api/tasks",
    tags=["tasks"],
    dependencies=[Depends(operator_auth)],
)

#: The path parameter every route takes.
TaskId = Annotated[int, PathParam(description="The task id, unique across runs.")]

#: The attempt statuses that make a transcript ``live``: the body is
#: still executing, or it is parked on a request and will go on writing
#: once that request is answered (04 §Waiting).
LIVE: Final = frozenset({rows.TaskStatus.in_progress, rows.TaskStatus.waiting})

#: The default and the maximum of ``?limit=`` on ``/{id}/stream``. The
#: same pair ``/api/runs/{id}/events`` uses, and for the same reason: one
#: page of history is never larger than one SSE replay (08 §Events).
DEFAULT_CHUNK_LIMIT: Final = 500
MAX_CHUNK_LIMIT: Final = 5000


# --------------------------------------------------------------------------
# The collaborators, and what their absence means
# --------------------------------------------------------------------------


def _store(request: Request, task_id: int) -> Store:
    """The store this task would be in, or the 404 there is no task without.

    ``create_app()`` takes its collaborators rather than building them
    (04 §Shutdown), so an application with no store is a real thing — the
    OpenAPI dump is one. It holds no attempts, so the honest answer to
    "give me this task" is that it does not exist, not a 500 about the
    server's own wiring.
    """

    store: Store | None = request.app.state.store
    if store is None:
        raise NotFound(f"task {task_id} does not exist: this server has no store")
    return store


def _engine(request: Request, task_id: int) -> Engine:
    """The engine a verb on this task needs, or the same 404."""

    engine: Engine | None = request.app.state.engine
    if engine is None:
        raise NotFound(f"task {task_id} does not exist: this server runs no workflows")
    return engine


async def _task(reader: Reader, task_id: int) -> rows.TaskRow:
    """The attempt, or 404 ``not_found``."""

    task = await reader.tasks.get(task_id)
    if task is None:
        raise NotFound(f"task {task_id} does not exist")
    return task


# --------------------------------------------------------------------------
# The reads
# --------------------------------------------------------------------------


@router.get("/{task_id}", summary="One attempt and what was submitted for it")
async def get_task(request: Request, task_id: TaskId) -> TaskDetail:
    """The operator view of a task: 08's ``TaskRow`` plus ``submissions``.

    Every accepted submission, oldest first, because "last valid wins"
    (D5) is a rule about which one the body reads and not about which
    ones happened: an operator reading a repaired attempt wants the
    rejected shape and the accepted one.

    No token, in this response or any other: a task token is
    header-only (12 §Task tokens), and ``TaskDetail`` has no field that
    could carry one.
    """

    store = _store(request, task_id)
    async with store.reader() as reader:
        task = await _task(reader, task_id)
        submissions = await reader.submissions.list(task_id)
    return TaskDetail.of_task(task, submissions)


@router.get("/{task_id}/stream", summary="A page of a task's agent transcript")
async def get_stream(
    request: Request,
    task_id: TaskId,
    after: Annotated[
        int, Query(ge=0, description="Return chunks after this sequence number.")
    ] = 0,
    limit: Annotated[
        int, Query(ge=1, le=MAX_CHUNK_LIMIT, description="How many chunks to return.")
    ] = DEFAULT_CHUNK_LIMIT,
) -> StreamOut:
    """The chunks after ``after``, in transcript order (08 §Tasks).

    ``after=0`` is the whole transcript from the start, which is what a
    tab opening on a finished attempt asks for; a client following a
    live one passes the ``seq_to`` of the ephemeral ``task.stream`` event
    it just received (18) and appends what comes back.
    """

    store = _store(request, task_id)
    async with store.reader() as reader:
        task = await _task(reader, task_id)
        chunks = await reader.stream.list_after(task_id, after, limit)
        last_seq = await reader.stream.last_seq(task_id)
    return StreamOut(
        chunks=[StreamChunk.of(chunk) for chunk in chunks],
        last_seq=last_seq,
        live=task.status in LIVE,
    )


# --------------------------------------------------------------------------
# The verbs
# --------------------------------------------------------------------------


@router.post("/{task_id}/retry", summary="Queue another attempt of a task")
async def retry_task(request: Request, task_id: TaskId) -> TaskRef:
    """Enqueue the next attempt of a task that has stopped.

    Same node, same payload, same branch and the same ``created``, so a
    retry keeps its place in the dispatch order (``Ops.retry``). Refused
    with 409 ``conflict`` while the task is still going: a second attempt
    of a task that already has one is two attempts of one task.
    """

    engine = _engine(request, task_id)
    task = await engine.ops.retry(task_id)
    return TaskRef(task_id=task.id)


@router.post("/{task_id}/move", summary="Move a task's work to another node")
async def move_task(request: Request, task_id: TaskId, body: Move) -> TaskRef:
    """Cancel the attempt and enqueue its payload at ``node``.

    409 ``conflict`` when ``node`` is a **join** (04 §Fan-in): a join is
    dispatched by its arrivals and called with all of them, so a task
    moved into one would be a join attempt holding a single branch's
    payload, with no arrival recorded and a run left waiting for
    branches that already landed.
    """

    engine = _engine(request, task_id)
    moved = await engine.ops.move(task_id, body.node)
    return TaskRef(task_id=moved.id)


@router.post("/{task_id}/status", summary="Write a task's status")
async def set_status(request: Request, task_id: TaskId, body: SetStatus) -> Ok:
    """Put the task in one of the three statuses an operator may write.

    ``ready`` re-dispatches it and re-opens a terminal run, ``cancelled``
    stops it and ``dead_letter`` files it as failed for good; the other
    four statuses are the engine's record of what happened and are not an
    operator's to declare, which is why the body's field is a
    ``Literal`` and a fourth value is a 422 before the engine is reached.
    """

    engine = _engine(request, task_id)
    await engine.ops.set_status(task_id, body.status)
    return Ok()

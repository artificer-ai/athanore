"""One attempt of one node, from claim to outcome (04 §Running an attempt).

:func:`run_attempt` is where the three rules meet the store. The
signature was the graph, so the body is called with an ``EdgeRef`` per
edge and its payload in its slot; the return value is the routing, so
:func:`~athanore.engine.routing.interpret` turns it into transitions and
this module writes them; the exception is the failure policy, so
:func:`~athanore.engine.errors.is_retryable` decides between a retry and
a dead-letter. Nothing here knows that agents exist.

The shape of the function is three transactions and a ``finally``:

1. one that announces the attempt (``task.started``, and ``run.started``
   on the first claim of a run);
2. the body call, under the node's ``timeout`` and **outside** every unit
   of work — a `uow` holds the writer lock, and one that spanned a body
   would hold it for the hours an agent turn can take (`AGENTS.md`
   §Durable by default);
3. one that records the outcome: the task finished, every transition
   enqueued or recorded as an arrival, and the run completed or failed
   if this was the last of it.

The ``finally`` runs on every path, cancellation included: the
transcript is flushed and closed, the pool slot goes back, the live
context is dropped and the scheduler is woken. A path that skipped it
would leak a slot, and under the default ``workers=1`` that is the whole
engine.

Two decisions are worth stating here rather than leaving to the reader:

- **A cancelled attempt writes no status.** An operator op has already
  recorded ``cancelled``; a shutdown deliberately leaves the row
  ``in_progress`` for recovery to reset (D52). Writing a status here is
  how a graceful restart turns into lost work.
- **The completion check is "no pending tasks", not "no transitions".**
  03 invariant 4 says a run is `completed` only when nothing is pending,
  no join has partial arrivals, and the last branch had no successors —
  but it also says that nothing pending *with* a partial join is
  `failed`, and that case arrives on a task which *did* transition: the
  last branch of a fan-out that transitions into a join which cannot
  fire. So quiescence is what opens the question, and the two answers
  are the invariant's (D102) — but only for a run that is still
  `running`. A run another branch already failed by dead-lettering is
  left alone: 03 §State machines re-opens a terminal run by
  retry/rerun/move and by nothing else, so settling it again would
  either swallow the failure or report the stall it caused twice
  (D103).
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from typing import Any, Final, Protocol

from athanore.engine.context import TaskContext, bind
from athanore.engine.errors import is_retryable
from athanore.engine.live import LiveRegistry
from athanore.engine.pools import Lease
from athanore.engine.routing import interpret, is_fan_out
from athanore.engine.services import TaskServices
from athanore.events.model import Event
from athanore.events.names import EventName
from athanore.events.payloads import (
    BranchFrame as FrameSummary,
)
from athanore.events.payloads import (
    EventModel,
    JoinArrived,
    RunCompleted,
    RunFailed,
    RunStarted,
    TaskDeadLettered,
    TaskDone,
    TaskEnqueued,
    TaskFailed,
    TaskStarted,
)
from athanore.graph import EdgeRef, Graph, GraphError, Node, Transition, jsonable
from athanore.logging import bind_attempt
from athanore.settings import AthanoreSettings
from athanore.store.clock import now
from athanore.store.repos.joins import JOIN_REASON, LINEAGE_FROM, LINEAGE_REASON
from athanore.store.repos.tasks import ClaimedTask
from athanore.store.rows import (
    BranchFrame,
    LogAuthor,
    LogKind,
    RunRow,
    RunStatus,
    TaskRow,
    TaskStatus,
)
from athanore.store.uow import Store, UnitOfWork

#: The ``lineage.reason`` of a task enqueued by a plain transition and of
#: one enqueued by the engine's own retry (03 §Task).
TRANSITION_REASON: Final = "transition"
RETRY_REASON: Final = "retry"

#: The ``code`` of a run that fell quiet with a join still short of its
#: branches (18 §Runs, 03 invariant 4).
JOIN_INCOMPLETE: Final = "join_incomplete"


class RunnerEngine(Protocol):
    """What :func:`run_attempt` needs of the engine (T027 supplies it).

    A protocol rather than an import, so the runner can be exercised
    against the small stub 17 §T024 describes: the real
    :class:`athanore.engine.Engine` is T027's, and it satisfies this
    structurally. Read-only properties, because an implementation is
    free to hold ``graphs`` as a ``dict``.
    """

    @property
    def store(self) -> Store: ...

    @property
    def settings(self) -> AthanoreSettings: ...

    @property
    def live(self) -> LiveRegistry: ...

    @property
    def graphs(self) -> Mapping[str, Graph]: ...

    def notify(self) -> None:
        """Wake the scheduler: this attempt may have made work ready."""
        ...


async def run_attempt(engine: RunnerEngine, claimed: ClaimedTask, lease: Lease) -> None:
    """Run one attempt of ``claimed`` and record what it did.

    ``claimed`` comes from :meth:`~athanore.store.repos.tasks.TaskRepo.claim_ready`,
    which already flipped the row to ``in_progress`` and minted the token
    this attempt authenticates with; ``lease`` is the pool slot the
    scheduler took for it, and this function is what gives it back.

    Returns when the attempt has ended, however it ended. The only
    exception that leaves here is ``asyncio.CancelledError`` — an
    operator cancelling the task, or a shutdown — which is re-raised with
    no status written (04 §Shutdown).
    """

    task = claimed.task
    services: TaskServices | None = None
    try:
        run = await _load_run(engine.store, task.run_id)
        graph = _load_graph(engine, run)
        services = TaskServices(
            engine.store,
            run_id=task.run_id,
            task_id=task.id,
            node=task.node,
            workflow=run.workflow,
            flush_interval=engine.settings.stream_flush_interval,
        )
        context = TaskContext(
            run_id=task.run_id,
            task_id=task.id,
            workflow=run.workflow,
            node=task.node,
            attempt=task.attempt,
            token=claimed.token,
            api_base=_api_base(engine.settings),
            services=services,
        )
        engine.live.register(context)
        with (
            bind_attempt(
                run_id=task.run_id,
                task_id=str(task.id),
                node=task.node,
                workflow=run.workflow,
                attempt=task.attempt,
            ),
            bind(context),
        ):
            await _announce_start(engine, claimed)
            node: Node | None = None
            try:
                node = _load_node(graph, task)
                value = await _call_body(node, task, context)
                await _record_success(engine, task, node, graph, value)
            except asyncio.CancelledError:
                # Not a failure: the op that cancelled recorded `cancelled`,
                # and a shutdown leaves the row for recovery (D52).
                raise
            except Exception as exc:
                await _record_failure(engine, task, node, services, exc)
    finally:
        if services is not None:
            await services.stream.close()
        lease.release()
        engine.live.unregister(task.id)
        engine.notify()


# --------------------------------------------------------------------------
# Loading what the attempt runs against
# --------------------------------------------------------------------------


async def _load_run(store: Store, run_id: str) -> RunRow:
    """The run this attempt belongs to.

    A read, not a unit of work: nothing is written until the attempt is
    announced. Its absence is impossible rather than unlikely — a task
    row is a child of its run and cascades with it — so it raises.
    """

    async with store.reader() as reader:
        run = await reader.runs.get(run_id)
    if run is None:  # pragma: no cover - tasks cascade with their run
        raise RuntimeError(f"task claimed for run {run_id!r}, which does not exist")
    return run


def _load_graph(engine: RunnerEngine, run: RunRow) -> Graph:
    """The finalized graph of ``run``'s workflow.

    Also impossible to miss: the claim only selects runs whose workflow
    is registered on the pool that claimed them (04 §Dispatch order), and
    a run of an unregistered workflow never dispatches (04 §Recovery).
    """

    graph = engine.graphs.get(run.workflow)
    if graph is None:  # pragma: no cover - the claim filters by workflow
        raise RuntimeError(
            f"run {run.id!r} is of workflow {run.workflow!r}, which is not registered"
        )
    return graph


def _load_node(graph: Graph, task: TaskRow) -> Node:
    """The node this task is an attempt of.

    A ``GraphError`` when the workflow no longer declares it, which is
    what a node renamed or deleted while a run was queued looks like.
    That dead-letters the task on this attempt (D42): the code defect is
    real, every retry would reproduce it, and the operator can move the
    task to a node that does exist.
    """

    node = graph.nodes.get(task.node)
    if node is None:
        raise GraphError(
            f"workflow {graph.name!r} has no node {task.node!r}; "
            f"its nodes are {sorted(graph.nodes)}"
        )
    return node


def _api_base(settings: AthanoreSettings) -> str:
    """What an agent of this attempt is told to call (04 §TaskContext)."""

    if settings.public_url is None:  # pragma: no cover - the validator fills it
        raise RuntimeError("settings.public_url is unset")
    return settings.public_url


# --------------------------------------------------------------------------
# The attempt
# --------------------------------------------------------------------------


async def _announce_start(engine: RunnerEngine, claimed: ClaimedTask) -> None:
    """Publish ``task.started``, and ``run.started`` on a run's first claim.

    The rows were written by the claim, in its transaction; this one
    carries the events, because the claim does not know which of the
    tasks it took this process actually went on to run.
    """

    task = claimed.task
    async with engine.store.uow() as uow:
        uow.emit(
            _event(
                task.run_id,
                task.id,
                EventName.task_started,
                TaskStarted(node=task.node, attempt=task.attempt),
            )
        )
        if claimed.run_started:
            uow.emit(
                _event(
                    task.run_id,
                    None,
                    EventName.run_started,
                    RunStarted(task_id=task.id, node=task.node),
                )
            )


async def _call_body(node: Node, task: TaskRow, context: TaskContext) -> Any:
    """Call the node body with its edges and its payload, under its timeout.

    A declared payload slot is always bound, ``None`` included: the
    engine never omits a parameter the signature asked for, and a body
    that wants a default writes ``*, payload=None`` (04 §Routing edge
    cases).

    The ``asyncio.Timeout`` is stashed on the context because a body that
    parks on a human gives its slot back and comes back later, and T026
    reschedules the deadline by the time it waited (04 §Waiting).
    """

    edge_refs = [EdgeRef(edge) for edge in node.edges]
    kwargs: dict[str, Any] = {}
    if node.payload_param is not None:
        kwargs[node.payload_param] = task.payload
    async with asyncio.timeout(node.timeout or None) as scope:
        # The runner owns this field; `context.py` declares it for exactly
        # this assignment and T026's reschedule.
        context._timeout = scope  # pyright: ignore[reportPrivateUsage]
        return await node.fn(*edge_refs, **kwargs)


# --------------------------------------------------------------------------
# Success
# --------------------------------------------------------------------------


async def _record_success(
    engine: RunnerEngine,
    task: TaskRow,
    node: Node,
    graph: Graph,
    value: Any,
) -> None:
    """Interpret the return value and write the whole outcome in one uow.

    Interpretation happens first and outside the transaction: a
    ``GraphError`` from an ambiguous return or an undeclared edge is the
    attempt's failure (rule 3), and it must not be one that rolled back a
    half-written transaction.
    """

    transitions = interpret(node, value)
    fanning_out = is_fan_out(value)
    terminal = not transitions
    async with engine.store.uow() as uow:
        await uow.tasks.finish(
            task.id,
            TaskStatus.done.value,
            result=jsonable(value),
            terminal=terminal,
        )
        for index, transition in enumerate(transitions):
            frames = _child_frames(
                task, transition, index, len(transitions), fanning_out
            )
            target = graph.nodes[transition.target]
            if target.join:
                await _record_arrival(uow, task, target, transition, frames)
            else:
                await _enqueue_transition(uow, task, target, transition, frames)
        uow.emit(
            _event(
                task.run_id,
                task.id,
                EventName.task_done,
                TaskDone(
                    node=task.node,
                    attempt=task.attempt,
                    transitions=[transition.target for transition in transitions],
                    terminal=terminal,
                ),
            )
        )
        await _settle_run(uow, task, terminal)


def _child_frames(
    task: TaskRow,
    transition: Transition,
    index: int,
    count: int,
    fanning_out: bool,
) -> list[BranchFrame]:
    """The branch stack a child of this transition runs under.

    A single transition copies the parent's stack unchanged; a fan-out
    pushes a frame naming itself, this branch's index, the width of the
    fan-out and the payload that branch was given — which is the
    branch's identity (04 §Branch frames, D4).
    """

    frames = list(task.branch)
    if fanning_out:
        frames.append(
            BranchFrame(
                fanout=task.id,
                index=index,
                count=count,
                key=jsonable(transition.payload),
            )
        )
    return frames


async def _enqueue_transition(
    uow: UnitOfWork,
    task: TaskRow,
    target: Node,
    transition: Transition,
    frames: Sequence[BranchFrame],
) -> None:
    """Enqueue one ordinary transition and announce it."""

    priority, explicit = _dispatch_key(target)
    child = await uow.tasks.enqueue(
        task.run_id,
        target.name,
        transition.payload,
        priority,
        explicit,
        lineage={LINEAGE_FROM: task.id, LINEAGE_REASON: TRANSITION_REASON},
        branch=frames,
    )
    uow.emit(
        _event(
            task.run_id,
            child.id,
            EventName.task_enqueued,
            TaskEnqueued(
                node=target.name,
                attempt=child.attempt,
                reason=TRANSITION_REASON,
                from_task=task.id,
                payload_present=transition.payload is not None,
                branch=_frame_summaries(frames),
            ),
        )
    )


async def _record_arrival(
    uow: UnitOfWork,
    task: TaskRow,
    target: Node,
    transition: Transition,
    frames: Sequence[BranchFrame],
) -> None:
    """Record a branch reaching a join, and dispatch the join if it is the last.

    The top frame is popped: it says which fan-out this branch belongs
    to, which branch it is, and how many there are. Routing into a join
    with no frame on the stack is a ``GraphError`` — a join closes a
    fan-out, and one reached without one is a graph the author did not
    mean to write (04 §Arrival and dispatch).
    """

    if not frames:
        raise GraphError(
            f"node {task.node!r} routed into join {target.name!r} with no "
            f"fan-out frame on its branch; a join closes a fan-out"
        )
    frame = frames[-1]
    arrival = await uow.joins.arrive(
        run_id=task.run_id,
        join_node=target.name,
        fanout_task=frame.fanout,
        index=frame.index,
        key=frame.key,
        value=transition.payload,
        from_task=task.id,
        count=frame.count,
    )
    uow.emit(
        _event(
            task.run_id,
            task.id,
            EventName.join_arrived,
            JoinArrived(
                join=target.name,
                fanout_task=frame.fanout,
                index=frame.index,
                count=arrival.count,
                arrived=arrival.arrived,
                late=arrival.late,
            ),
        )
    )
    if arrival.late or arrival.arrived < arrival.count:
        return

    arrivals = await uow.joins.arrivals(task.run_id, target.name, frame.fanout)
    payload = [
        {
            "index": row.index,
            "key": row.key,
            "value": row.value,
            "from_task": row.from_task,
        }
        for row in arrivals
    ]
    senders = [row.from_task for row in arrivals if row.from_task is not None]
    outer = list(frames[:-1])
    priority, explicit = _dispatch_key(target)
    child = await uow.tasks.enqueue(
        task.run_id,
        target.name,
        payload,
        priority,
        explicit,
        lineage={
            LINEAGE_FROM: frame.fanout,
            LINEAGE_REASON: JOIN_REASON,
            "arrivals": senders,
        },
        branch=outer,
    )
    uow.emit(
        _event(
            task.run_id,
            child.id,
            EventName.task_enqueued,
            TaskEnqueued(
                node=target.name,
                attempt=child.attempt,
                reason=JOIN_REASON,
                from_task=frame.fanout,
                payload_present=True,
                branch=_frame_summaries(outer),
                arrivals=senders,
            ),
        )
    )


async def _settle_run(uow: UnitOfWork, task: TaskRow, terminal: bool) -> None:
    """End the run if this attempt was the last of it (03 invariant 4).

    A run that is no longer ``running`` is not settled at all: the
    question has already been answered, and 03 §State machines has no
    edge out of a terminal run that is not an operator's
    (retry/rerun/move re-open it). A dead-letter in one branch fails the
    run while a slower sibling is still in its body, and that sibling's
    outcome must not overwrite the verdict — with ``completed``, which
    would swallow the failure and make the run's status a race on which
    branch landed last, nor with a second ``failed``, which would emit a
    second ``run.failed`` and re-stamp ``finished`` for one stall
    (D103). The read is inside this transaction, so the status it sees
    is the one this write would replace.

    Then three outcomes, decided in this order:

    - something is still pending — nothing to settle;
    - a join is short of its branches and nothing will bring them, which
      is a deadlock rather than a completion: ``failed``, with
      ``join_incomplete`` naming the join;
    - this branch had no successors and no join is outstanding:
      ``completed``, with the output of the shape rule.

    A task that transitioned into a join that did not fire falls through
    all three: the run is not finished, and the branch that will finish
    it is the one that has not arrived yet.
    """

    run = await uow.runs.get(task.run_id)
    if run is None or run.status is not RunStatus.running:
        return
    if await uow.tasks.has_pending(task.run_id):
        return
    partial = await uow.joins.incomplete(task.run_id)
    if partial:
        error = "; ".join(
            f"{JOIN_INCOMPLETE}: {join.join_node} has {join.arrived} "
            f"of {join.count} arrivals"
            for join in partial
        )
        await uow.runs.set_status(task.run_id, RunStatus.failed.value, finished=now())
        uow.emit(
            _event(
                task.run_id,
                None,
                EventName.run_failed,
                RunFailed(
                    node=task.node,
                    task_id=task.id,
                    error=error,
                    code=JOIN_INCOMPLETE,
                ),
            )
        )
        return
    if not terminal:
        return
    terminals = await uow.tasks.terminal_tasks(task.run_id)
    output = _output(terminals)
    await uow.runs.update(
        task.run_id,
        status=RunStatus.completed.value,
        output=output,
        finished=now(),
    )
    uow.emit(
        _event(
            task.run_id,
            None,
            EventName.run_completed,
            RunCompleted(
                node=task.node,
                task_id=task.id,
                output=output,
                terminal_tasks=[row.id for row in terminals],
            ),
        )
    )


def _output(terminals: Sequence[TaskRow]) -> Any:
    """A run's output from its terminal tasks (04 §Routing edge cases, D58).

    One terminal task — a linear run, or a fan-out closed by a join — is
    its value; several independently terminating branches are the list of
    theirs, in branch order. Deterministic by shape, never by which
    branch finished first: ``terminal_tasks`` orders by the frame index
    path.
    """

    if len(terminals) == 1:
        return terminals[0].result
    return [row.result for row in terminals]


# --------------------------------------------------------------------------
# Failure
# --------------------------------------------------------------------------


async def _record_failure(
    engine: RunnerEngine,
    task: TaskRow,
    node: Node | None,
    services: TaskServices,
    exc: Exception,
) -> None:
    """Fail the attempt, and either retry it or dead-letter it (rule 3).

    ``node`` is ``None`` when the failure was the node lookup itself. It
    only feeds the retry budget, and that failure is a ``GraphError``,
    which is never retried — so the budget is the server default and
    never consulted.

    The work-log line is appended after the transaction and in its own,
    which is where :class:`~athanore.engine.services.LogService` puts
    every entry: it is the human-readable record of a failure the store
    already holds, not a second state change the failure depends on.
    """

    error = repr(exc)
    retryable = is_retryable(exc)
    budget = _retry_budget(node, engine.settings)
    will_retry = retryable and task.attempt < budget
    async with engine.store.uow() as uow:
        await uow.tasks.finish(task.id, TaskStatus.failed.value, error=error)
        retry_task_id: int | None = None
        if will_retry:
            retry = await uow.tasks.enqueue(
                task.run_id,
                task.node,
                task.payload,
                task.priority,
                task.explicit,
                attempt=task.attempt + 1,
                created=task.created,
                lineage={LINEAGE_FROM: task.id, LINEAGE_REASON: RETRY_REASON},
                branch=task.branch,
            )
            retry_task_id = retry.id
            uow.emit(
                _event(
                    task.run_id,
                    retry.id,
                    EventName.task_enqueued,
                    TaskEnqueued(
                        node=task.node,
                        attempt=retry.attempt,
                        reason=RETRY_REASON,
                        from_task=task.id,
                        payload_present=task.payload is not None,
                        branch=_frame_summaries(task.branch),
                    ),
                )
            )
        uow.emit(
            _event(
                task.run_id,
                task.id,
                EventName.task_failed,
                TaskFailed(
                    node=task.node,
                    attempt=task.attempt,
                    error=error,
                    retryable=retryable,
                    will_retry=will_retry,
                    retry_task_id=retry_task_id,
                ),
            )
        )
        if not will_retry:
            await uow.tasks.set_status(task.id, TaskStatus.dead_letter.value)
            uow.emit(
                _event(
                    task.run_id,
                    task.id,
                    EventName.task_dead_lettered,
                    TaskDeadLettered(node=task.node, attempt=task.attempt, error=error),
                )
            )
            await uow.runs.set_status(
                task.run_id, RunStatus.failed.value, finished=now()
            )
            uow.emit(
                _event(
                    task.run_id,
                    None,
                    EventName.run_failed,
                    RunFailed(node=task.node, task_id=task.id, error=error),
                )
            )
    await services.log.append(
        f"attempt {task.attempt} failed: {exc}",
        author=LogAuthor.engine,
        kind=LogKind.failure,
    )


def _retry_budget(node: Node | None, settings: AthanoreSettings) -> int:
    """How many attempts this node gets before it dead-letters.

    ``retries`` of ``None`` means the server default (04 §Node options);
    ``retries=0`` therefore means no retry at all, rather than the
    default, which is the only reading under which writing it does
    anything (D102).
    """

    if node is None or node.retries is None:
        return settings.max_retries
    return node.retries


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------


def _dispatch_key(target: Node) -> tuple[int, bool]:
    """The priority a task at ``target`` is enqueued with (04 §Dispatch order).

    An explicit ``priority`` on the node is used as given and flagged, so
    it beats every generation-based task in the run; otherwise the key is
    ``-generation``, which dispatches downstream work first.
    """

    if target.priority is not None:
        return target.priority, True
    return -target.generation, False


def _frame_summaries(frames: Sequence[BranchFrame]) -> list[FrameSummary]:
    """A branch stack as 18 puts it on the wire: without the keys.

    A frame's ``key`` is the payload that branch was given and may be as
    large as the payload itself, so the event carries the shape of the
    stack and a reader fetches the task for the rest (18 §Rules).
    """

    return [
        FrameSummary(fanout=frame.fanout, index=frame.index, count=frame.count)
        for frame in frames
    ]


def _event(
    run_id: str, task_id: int | None, name: EventName, data: EventModel
) -> Event:
    """One event of the vocabulary, with 18's envelope filled in."""

    return Event(
        run_id=run_id,
        task_id=task_id,
        name=name,
        data=data.model_dump(),
        created=now(),
    )


__all__ = [
    "JOIN_INCOMPLETE",
    "RETRY_REASON",
    "TRANSITION_REASON",
    "RunnerEngine",
    "run_attempt",
]

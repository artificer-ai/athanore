"""The operator's verbs: what a human can do to a run (04 §Operator operations).

Everything the API, the CLI and the TUI can ask of a running engine is a
method here, and 04's table is the specification: one precondition, one
effect, one transaction. The shape is the same for all twelve:

1. read the rows the operation is about and refuse it if the
   precondition does not hold — :class:`~athanore.engine.errors.NotFound`,
   :class:`~athanore.engine.errors.UnknownWorkflow`,
   :class:`~athanore.engine.errors.UnknownNode` or
   :class:`~athanore.engine.errors.Conflict`, which T042 maps to status
   codes;
2. write the change and emit its events in **one** unit of work, so an
   operator action is atomic and a subscriber that fetches on receipt
   sees the state the event describes (03 invariant 7);
3. only then touch the live process — cancel the asyncio attempts,
   wake the scheduler.

Three rules are worth stating once, because every op that gets them
wrong gets them wrong the same way.

- **The transaction commits before an attempt is cancelled.** Cancelling
  first would let the runner's ``CancelledError`` arm run against a row
  that is still ``in_progress``, and the two would then disagree about
  what happened to the task. Ops that kill work therefore collect the
  ids inside the uow and call
  :meth:`~athanore.engine.scheduler.Scheduler.cancel_attempts` after the
  block has closed.
- **``notify()`` is for the ops that can make work dispatchable** —
  submit, resume, rerun, retry, move, ``set_status``, and the two that
  free capacity by ending work. Editing a title cannot dispatch
  anything, and waking the loop to discover that is a tick spent for
  nothing.
- **Re-dispatched work does not silently jump the queue.** ``retry``
  keeps the failed attempt's ``created``, because the dispatch order's
  last tiebreaker is ``created DESC`` and a fresh timestamp would put a
  flapping node in front of everything enqueued while it ran. ``move``
  takes a fresh one, because it is new work at a different node. The
  asymmetry is deliberate (04 §Operator operations).

Agents never appear here: an operator moves tasks, an agent submits
values, and nothing in this module knows that agents exist.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Final, Literal, Protocol, get_args

from athanore.engine.errors import Conflict, NotFound, UnknownNode, UnknownWorkflow
from athanore.engine.runner import (
    arrival_senders,
    arrivals_payload,
    dispatch_key,
    frame_summaries,
)
from athanore.engine.scheduler import Scheduler
from athanore.events.model import Event
from athanore.events.names import EventName
from athanore.events.payloads import (
    EventModel,
    LogAppended,
    RunCancelled,
    RunChanges,
    RunCreated,
    RunDeleted,
    RunPaused,
    RunReordered,
    RunResumed,
    RunUpdated,
    TaskCancelled,
    TaskEnqueued,
    TaskMoved,
    TaskStatusSet,
)
from athanore.graph import Graph, Node
from athanore.store.clock import now
from athanore.store.repos.joins import LINEAGE_FROM, LINEAGE_REASON
from athanore.store.repos.tasks import PENDING
from athanore.store.rows import (
    BranchFrame,
    LogAuthor,
    LogEntryRow,
    RunRow,
    RunStatus,
    TaskRow,
    TaskStatus,
)
from athanore.store.uow import Store, UnitOfWork

#: The ``lineage.reason`` of each task an operator operation enqueues
#: (03 §Task, 18 §Tasks). ``start`` is the one task a submission creates.
START_REASON: Final = "start"
RERUN_REASON: Final = "rerun"
MANUAL_RETRY_REASON: Final = "manual_retry"
MOVE_REASON: Final = "move"
SET_STATUS_REASON: Final = "set_status"

#: How much of a work-log entry ``log.appended`` carries (18 §Log and
#: stats). The same cap :class:`~athanore.engine.services.LogService`
#: applies, restated rather than imported: the services module is the
#: attempt's half of the log and this is the operator's, and neither is
#: below the other.
PREVIEW_CHARS: Final = 200

#: The node an operator's log entry is filed under when the run has no
#: single in-flight node to attribute it to (04 §Operator operations).
USER_NODE: Final = "user"

#: A task an attempt is actually inside: running, or parked on a human.
#: This is 03's ``current_nodes`` — a ``ready`` task is queued, not live,
#: and a note filed under the node it is queued at would claim that
#: something is happening there.
LIVE_TASKS: Final[tuple[str, str]] = (
    TaskStatus.in_progress.value,
    TaskStatus.waiting.value,
)

#: A run that has ended. 03 §State machines re-opens one by retry, rerun
#: or move and by nothing else, which is what :meth:`Ops._reopen` does.
TERMINAL_RUNS: Final[tuple[RunStatus, ...]] = (
    RunStatus.completed,
    RunStatus.failed,
    RunStatus.cancelled,
)

#: The run statuses ``pause`` accepts, and the one ``resume`` does
#: (04 §Operator operations).
PAUSABLE: Final[tuple[RunStatus, ...]] = (RunStatus.queued, RunStatus.running)

#: The statuses ``set_status`` may write. The others are the engine's own
#: bookkeeping: an operator does not declare a task ``done``.
SettableStatus = Literal["ready", "cancelled", "dead_letter"]

#: The same three at runtime. The annotation is the contract for callers
#: that are type-checked; this is the check for the ones that are not.
SETTABLE: Final[tuple[str, ...]] = get_args(SettableStatus)


class OpsEngine(Protocol):
    """What :class:`Ops` needs of the engine it belongs to.

    A protocol rather than an import of :class:`athanore.engine.Engine`,
    which constructs this object: the real engine satisfies it
    structurally, and stating the four members here says exactly how much
    of the engine an operator operation is allowed to touch.
    """

    @property
    def store(self) -> Store: ...

    @property
    def graphs(self) -> dict[str, Graph]: ...

    @property
    def scheduler(self) -> Scheduler: ...

    def notify(self) -> None:
        """Wake the scheduler: this operation may have made work ready."""
        ...


class Ops:
    """The operator operations of one engine (04 §Operator operations)."""

    def __init__(self, engine: OpsEngine) -> None:
        self._engine = engine

    # ----------------------------------------------------------------------
    # Runs: submit, edit, reorder, pause, resume, append_log (T027a)
    # ----------------------------------------------------------------------

    async def submit(self, workflow: str, title: str, description: str = "") -> RunRow:
        """Queue a run of ``workflow`` and its one start task.

        The run is ``queued``, not ``running``: "waiting for a slot" is a
        state an operator can see, and the first claim of one of its
        tasks is what flips it (03 §Run). The start task's payload is
        ``{title, description}`` — the workflow's own input, which is why
        an edit of either afterwards does not rewrite it.

        Raises :class:`~athanore.engine.errors.UnknownWorkflow` when
        nothing of that name is registered, and
        :class:`~athanore.engine.errors.Conflict` for an empty title: a
        run with no title is unfindable in every list that shows one.
        """

        graph = self._graph(workflow)
        clean = _clean_title(title)
        node = graph.start_node
        priority, explicit = dispatch_key(node)
        async with self._engine.store.uow() as uow:
            run = await uow.runs.insert(workflow, clean, description)
            uow.emit(
                _event(
                    run.id,
                    None,
                    EventName.run_created,
                    RunCreated(workflow=workflow, title=clean, position=run.position),
                )
            )
            task = await uow.tasks.enqueue(
                run.id,
                node.name,
                {"title": clean, "description": description},
                priority,
                explicit,
                lineage={LINEAGE_REASON: START_REASON},
            )
            uow.emit(
                _event(
                    run.id,
                    task.id,
                    EventName.task_enqueued,
                    TaskEnqueued(
                        node=node.name,
                        attempt=task.attempt,
                        reason=START_REASON,
                        payload_present=True,
                        branch=[],
                    ),
                )
            )
        self._engine.notify()
        return run

    async def edit(
        self,
        run_id: str,
        title: str | None = None,
        description: str | None = None,
    ) -> RunRow:
        """Change a run's title, its description, or both.

        ``None`` means "leave it": an edit names the fields it changes,
        and ``run.updated`` carries only those — a ``changed`` block
        listing a field the operator never touched is a diff nobody can
        read. An edit that asks for the values already stored writes
        nothing and emits nothing.

        A title that is empty or only whitespace is a
        :class:`~athanore.engine.errors.Conflict`, on any run in any
        state: 04 §Operator operations gives ``edit`` one precondition
        and this is it.
        """

        async with self._engine.store.uow() as uow:
            run = await self._run(uow, run_id)
            fields: dict[str, Any] = {}
            if title is not None:
                clean = _clean_title(title)
                if clean != run.title:
                    fields["title"] = clean
            if description is not None and description != run.description:
                fields["description"] = description
            if not fields:
                return run
            updated = await uow.runs.update(run_id, **fields)
            if updated is None:  # pragma: no cover - the row was read above
                raise NotFound(f"run {run_id!r} does not exist")
            uow.emit(
                _event(
                    run_id,
                    None,
                    EventName.run_updated,
                    RunUpdated(changed=RunChanges(**fields)),
                )
            )
        return updated

    async def reorder(
        self,
        run_id: str,
        direction: int | None = None,
        index: int | None = None,
    ) -> int:
        """Move a run in the dispatch list, and return its position (D57).

        Exactly one of ``direction`` and ``index`` is given.
        ``direction`` is ``-1`` (up) or ``+1`` (down) and swaps with the
        neighbour; at either end there is no neighbour, so it is a no-op
        that reports the position the run already had. ``index`` is the
        **zero-based** list index, clamped to the list, and renumbers the
        runs it displaced.

        ``run.reordered`` is emitted only when the run actually moved: a
        no-op swap at the top of the list is an event that says nothing
        happened.

        Dispatch reads ``runs.position`` through the claim's join, so
        there is nothing to keep in sync and nothing to wake — the next
        claim sees the new order because it reads it.
        """

        if (direction is None) == (index is None):
            raise ValueError("reorder takes exactly one of direction and index")
        async with self._engine.store.uow() as uow:
            run = await self._run(uow, run_id)
            if direction is not None:
                if direction not in (-1, 1):
                    raise ValueError(f"direction must be -1 or 1, not {direction!r}")
                position = await uow.runs.swap_position(run_id, direction)
            elif index is not None:
                position = await uow.runs.move_position(run_id, index)
            else:  # pragma: no cover - the guard above refuses this
                raise ValueError("reorder takes exactly one of direction and index")
            if position is None:  # pragma: no cover - the row was read above
                raise NotFound(f"run {run_id!r} does not exist")
            if position != run.position:
                uow.emit(
                    _event(
                        run_id,
                        None,
                        EventName.run_reordered,
                        RunReordered(position=position, previous=run.position),
                    )
                )
        return position

    async def pause(self, run_id: str) -> RunRow:
        """Stop a run dispatching; let what is already running finish.

        The claim excludes ``paused`` runs (07 §Repositories), so pause is
        about the **next** task rather than the current one: an attempt in
        flight runs to its end, records its outcome and enqueues its
        successor, and that successor waits. Killing running work is
        :meth:`cancel`.

        Only a ``queued`` or ``running`` run can be paused; anything else
        is a :class:`~athanore.engine.errors.Conflict`.
        """

        async with self._engine.store.uow() as uow:
            run = await self._run(uow, run_id)
            if run.status not in PAUSABLE:
                raise Conflict(
                    f"run {run_id!r} is {run.status.value}, not queued or running"
                )
            paused = await uow.runs.set_status(run_id, RunStatus.paused.value)
            if paused is None:  # pragma: no cover - the row was read above
                raise NotFound(f"run {run_id!r} does not exist")
            uow.emit(_event(run_id, None, EventName.run_paused, RunPaused()))
        return paused

    async def resume(self, run_id: str) -> RunRow:
        """Let a paused run dispatch again.

        The run goes to ``running``, which is what 04 §Operator
        operations says and what the state machine of 03 draws: there is
        no record of what it was before it was paused, and inventing one
        would mean a second column that could disagree with this one.
        Only a ``paused`` run can be resumed.
        """

        async with self._engine.store.uow() as uow:
            run = await self._run(uow, run_id)
            if run.status is not RunStatus.paused:
                raise Conflict(f"run {run_id!r} is {run.status.value}, not paused")
            resumed = await uow.runs.set_status(run_id, RunStatus.running.value)
            if resumed is None:  # pragma: no cover - the row was read above
                raise NotFound(f"run {run_id!r} does not exist")
            uow.emit(_event(run_id, None, EventName.run_resumed, RunResumed()))
        self._engine.notify()
        return resumed

    async def append_log(self, run_id: str, text: str) -> LogEntryRow:
        """Add an operator note to a run's work log.

        The author is ``user``. The node is the run's single in-flight
        node — the one node with an ``in_progress`` or ``waiting`` task —
        and ``"user"`` when there is not exactly one,
        because a note filed under one branch of a fan-out claims a
        context it does not have.

        No ``task_id``: an operator note is about the run, not about an
        attempt (03 §LogEntry).
        """

        entry = text.strip()
        if not entry:
            raise Conflict("a log entry needs text")
        async with self._engine.store.uow() as uow:
            await self._run(uow, run_id)
            node = await self._current_node(uow, run_id)
            row = await uow.log.append(
                run_id=run_id,
                node=node,
                author=LogAuthor.user,
                text=text,
            )
            uow.emit(
                _event(
                    run_id,
                    None,
                    EventName.log_appended,
                    LogAppended(
                        log_id=row.id,
                        author=str(LogAuthor.user),
                        node=node,
                        preview=text[:PREVIEW_CHARS],
                    ),
                )
            )
        return row

    # ----------------------------------------------------------------------
    # Runs and tasks: cancel, delete (T027b)
    # ----------------------------------------------------------------------

    async def cancel(self, run_id: str) -> list[int]:
        """End a run and everything outstanding under it.

        Every ``ready``, ``in_progress`` or ``waiting`` task becomes
        ``cancelled`` and the run does too, in one transaction; the
        asyncio attempts are cancelled **after** it commits, so the
        runner's cancellation arm can never see a row this operation has
        not finished writing. The attempt writes no status of its own on
        the way out (D52) — the status is this transaction's, and that is
        what makes ``cancelled`` mean operator intent.

        Returns the ids that were cancelled. A run that has already ended
        is a :class:`~athanore.engine.errors.Conflict`: there is nothing
        to stop.
        """

        async with self._engine.store.uow() as uow:
            run = await self._run(uow, run_id)
            if run.status in TERMINAL_RUNS:
                raise Conflict(f"run {run_id!r} has already ended ({run.status.value})")
            task_ids = await self._cancel_tasks(uow, run_id, reason="cancel")
            await uow.runs.set_status(run_id, RunStatus.cancelled.value, finished=now())
            uow.emit(
                _event(
                    run_id,
                    None,
                    EventName.run_cancelled,
                    RunCancelled(cancelled_tasks=task_ids),
                )
            )
        self._engine.scheduler.cancel_attempts(task_ids)
        self._engine.notify()
        return task_ids

    async def delete(self, run_id: str) -> None:
        """Cancel a run, then remove it and every row under it.

        Two transactions, in this order and for this reason: the first
        marks the outstanding tasks ``cancelled`` and the attempts are
        killed against rows that still exist, and only then does the
        second delete the run. Deleting first would leave a live attempt
        writing against rows that are gone.

        The delete relies on the schema's cascades for the eight child
        tables and sweeps ``events`` itself (07 §Schema notes), so
        ``run.deleted`` — emitted by this transaction's outbox, after the
        sweep — is the last event of the run and reaches SSE clients
        only.

        A run in any state can be deleted; that is 04's precondition, and
        the only one.
        """

        async with self._engine.store.uow() as uow:
            run = await self._run(uow, run_id)
            task_ids = await self._cancel_tasks(uow, run_id, reason="delete")
        self._engine.scheduler.cancel_attempts(task_ids)
        async with self._engine.store.uow() as uow:
            if not await uow.runs.delete(run_id):  # pragma: no cover - read above
                raise NotFound(f"run {run_id!r} does not exist")
            uow.emit(
                _event(
                    run_id,
                    None,
                    EventName.run_deleted,
                    RunDeleted(workflow=run.workflow, title=run.title),
                )
            )
        self._engine.notify()

    # ----------------------------------------------------------------------
    # Tasks: rerun, retry, move, set_status (T027b)
    # ----------------------------------------------------------------------

    async def rerun(self, run_id: str, node: str) -> TaskRow:
        """Run a node again, with the payload and branch it last had.

        The attempt count continues rather than restarting: the new task
        is one past the highest attempt that node has reached in this
        run, so the timeline reads as one sequence per node however many
        times an operator intervened.

        A **join** node replays the arrivals the store holds rather than
        the payload the join task was given, which is what makes a rerun
        the remedy for a branch that arrived late: T024b enqueues no
        second join task for a late arrival, and this is where that
        branch reaches the join body (04 §Failure and operator
        semantics). A join that never fired has no arrivals to replay and
        is refused.

        A terminal run re-opens (03 §State machines).
        """

        async with self._engine.store.uow() as uow:
            run = await self._run(uow, run_id)
            target = self._node(self._graph(run.workflow), node)
            last = await uow.tasks.last_for_node(run_id, node)
            payload: Any = None
            branch: Sequence[BranchFrame] = ()
            lineage: dict[str, Any] = {LINEAGE_REASON: RERUN_REASON}
            if last is not None:
                payload = last.payload
                branch = last.branch
                lineage[LINEAGE_FROM] = last.id
            if target.join:
                payload, senders, fanout = await self._join_replay(
                    uow, run_id, target, last
                )
                # A join task's `lineage.from` is the fan-out it closes,
                # never the task it replaces: it is the only durable
                # record of which fan-out was dispatched (D102), and a
                # second rerun reads it to find these arrivals again.
                lineage[LINEAGE_FROM] = fanout
                lineage["arrivals"] = senders
            attempt = await self._next_attempt(uow, run_id, node)
            task = await self._enqueue(
                uow,
                run_id,
                target,
                payload,
                reason=RERUN_REASON,
                lineage=lineage,
                branch=branch,
                attempt=attempt,
                from_task=lineage.get(LINEAGE_FROM),
                arrivals=lineage.get("arrivals"),
            )
            await self._reopen(uow, run)
        self._engine.notify()
        return task

    async def retry(self, task_id: int) -> TaskRow:
        """Queue another attempt of a task that has stopped.

        Same node, same payload, same branch and the same dispatch key —
        and the same ``created``, which is the whole point: ``created
        DESC`` is the dispatch order's last tiebreaker, so a retry that
        took a fresh timestamp would overtake everything enqueued while
        the attempt it replaces was running. :meth:`move` is the op that
        does take a fresh one, because it is new work.

        Refused while the task is still going — ``ready``,
        ``in_progress`` or ``waiting`` — because a second attempt of a
        task that has one is two attempts of one task. A terminal run
        re-opens.
        """

        async with self._engine.store.uow() as uow:
            task = await self._task(uow, task_id)
            if task.status.value in PENDING:
                raise Conflict(
                    f"task {task_id} is {task.status.value}; it has not stopped"
                )
            run = await self._run(uow, task.run_id)
            # Validation only: a retry keeps the failed attempt's own
            # dispatch key, so nothing is read off the node — but a task
            # whose node the workflow no longer declares would only
            # dead-letter again, and saying so now is the better answer.
            self._node(self._graph(run.workflow), task.node)
            retry = await uow.tasks.enqueue(
                task.run_id,
                task.node,
                task.payload,
                task.priority,
                task.explicit,
                attempt=task.attempt + 1,
                created=task.created,
                lineage={LINEAGE_FROM: task.id, LINEAGE_REASON: MANUAL_RETRY_REASON},
                branch=task.branch,
            )
            uow.emit(
                _event(
                    task.run_id,
                    retry.id,
                    EventName.task_enqueued,
                    TaskEnqueued(
                        node=task.node,
                        attempt=retry.attempt,
                        reason=MANUAL_RETRY_REASON,
                        from_task=task.id,
                        payload_present=task.payload is not None,
                        branch=frame_summaries(task.branch),
                    ),
                )
            )
            await self._reopen(uow, run)
        self._engine.notify()
        return retry

    async def move(self, task_id: int, node: str) -> TaskRow:
        """Cancel a task and enqueue its work at another node.

        The payload and the branch stack travel with it — the payload is
        the branch's identity under a fan-out, so a move inside a branch
        stays in that branch — but ``created`` does not: a move is new
        work and goes to the back of the queue, where a :meth:`retry`
        keeps its place. Test both; the asymmetry is the point.

        A **join** target is refused. A join task is dispatched by its
        arrivals and is called with all of them (04 §Fan-in); a task
        moved into one would be a join attempt with a single branch's
        payload and no arrival recorded, which is a run that then waits
        forever for branches that already arrived.

        Only an outstanding task is cancelled by the move. One that has
        already finished keeps the status it earned — a ``dead_letter``
        row moved to another node is still the record of an attempt that
        died, and overwriting it with ``cancelled`` would lose that.

        The attempt, if this process is running one, is cancelled after
        the transaction commits. A terminal run re-opens.
        """

        async with self._engine.store.uow() as uow:
            task = await self._task(uow, task_id)
            run = await self._run(uow, task.run_id)
            target = self._node(self._graph(run.workflow), node)
            if target.join:
                raise Conflict(
                    f"node {node!r} is a join; a task cannot be moved into one"
                )
            if task.status.value in PENDING:
                await self._cancel_task(uow, task, reason="move")
            moved = await self._enqueue(
                uow,
                task.run_id,
                target,
                task.payload,
                reason=MOVE_REASON,
                lineage={LINEAGE_FROM: task.id, LINEAGE_REASON: MOVE_REASON},
                branch=task.branch,
                from_task=task.id,
            )
            uow.emit(
                _event(
                    task.run_id,
                    task.id,
                    EventName.task_moved,
                    TaskMoved(node=task.node, to=node, new_task_id=moved.id),
                )
            )
            await self._reopen(uow, run)
        self._engine.scheduler.cancel_attempts([task_id])
        self._engine.notify()
        return moved

    async def set_status(self, task_id: int, status: SettableStatus) -> TaskRow:
        """Put a task in one of the three statuses an operator may write.

        ``ready`` re-dispatches it, ``cancelled`` stops it and
        ``dead_letter`` files it as failed for good. The other four
        statuses are the engine's own record of what happened and are not
        an operator's to declare.

        Whatever the target, an attempt this process is running is
        cancelled: the row no longer describes what that attempt is
        doing, and leaving it alive would put two attempts on one task as
        soon as ``ready`` was claimed again.

        ``cancelled`` emits ``task.cancelled`` beside ``task.status_set``:
        18's ``reason`` vocabulary has a ``set_status`` member for
        exactly this path, and a client that reacts to a task being
        stopped should not have to know which of two ops stopped it.
        ``ready`` re-opens a terminal run.
        """

        if status not in SETTABLE:
            raise ValueError(
                f"a task cannot be set to {status!r}; an operator may write "
                f"{list(SETTABLE)}"
            )
        target_status = TaskStatus(status)
        async with self._engine.store.uow() as uow:
            task = await self._task(uow, task_id)
            previous = task.status
            row = await uow.tasks.set_status(task_id, target_status.value)
            if row is None:  # pragma: no cover - the row was read above
                raise NotFound(f"task {task_id} does not exist")
            uow.emit(
                _event(
                    task.run_id,
                    task_id,
                    EventName.task_status_set,
                    TaskStatusSet(
                        node=task.node,
                        from_=previous.value,
                        to=target_status.value,
                    ),
                )
            )
            if target_status is TaskStatus.cancelled:
                uow.emit(
                    _event(
                        task.run_id,
                        task_id,
                        EventName.task_cancelled,
                        TaskCancelled(
                            node=task.node,
                            from_=previous.value,
                            reason=SET_STATUS_REASON,
                        ),
                    )
                )
            if target_status is TaskStatus.ready:
                run = await self._run(uow, task.run_id)
                await self._reopen(uow, run)
        self._engine.scheduler.cancel_attempts([task_id])
        self._engine.notify()
        return row

    # ----------------------------------------------------------------------
    # Shared
    # ----------------------------------------------------------------------

    def _graph(self, workflow: str) -> Graph:
        """The finalized graph of ``workflow``, or refuse the operation."""

        graph = self._engine.graphs.get(workflow)
        if graph is None:
            raise UnknownWorkflow(
                f"workflow {workflow!r} is not registered; registered workflows "
                f"are {sorted(self._engine.graphs)}"
            )
        return graph

    def _node(self, graph: Graph, node: str) -> Node:
        """One node of ``graph``, or refuse the operation."""

        target = graph.nodes.get(node)
        if target is None:
            raise UnknownNode(
                f"workflow {graph.name!r} has no node {node!r}; its nodes are "
                f"{sorted(graph.nodes)}"
            )
        return target

    async def _run(self, uow: UnitOfWork, run_id: str) -> RunRow:
        """The run, read inside the operation's transaction."""

        run = await uow.runs.get(run_id)
        if run is None:
            raise NotFound(f"run {run_id!r} does not exist")
        return run

    async def _task(self, uow: UnitOfWork, task_id: int) -> TaskRow:
        """The task, read inside the operation's transaction."""

        task = await uow.tasks.get(task_id)
        if task is None:
            raise NotFound(f"task {task_id} does not exist")
        return task

    async def _current_node(self, uow: UnitOfWork, run_id: str) -> str:
        """The run's single in-flight node, or :data:`USER_NODE`.

        In-flight is ``in_progress`` or ``waiting`` — 03's
        ``current_nodes`` — so a run whose only task is queued files its
        operator notes under ``user``, exactly as v0 did.
        """

        nodes = {
            task.node
            for task in await uow.tasks.list_for_run(run_id)
            if task.status.value in LIVE_TASKS
        }
        if len(nodes) != 1:
            return USER_NODE
        return nodes.pop()

    async def _next_attempt(self, uow: UnitOfWork, run_id: str, node: str) -> int:
        """One past the highest attempt ``node`` has reached in this run."""

        attempts = [
            task.attempt
            for task in await uow.tasks.list_for_run(run_id)
            if task.node == node
        ]
        return max(attempts, default=0) + 1

    async def _join_replay(
        self,
        uow: UnitOfWork,
        run_id: str,
        target: Node,
        last: TaskRow | None,
    ) -> tuple[list[dict[str, Any]], list[int], int]:
        """The arrivals a rerun of join ``target`` replays, and their fan-out.

        The fan-out is read from the last join task's lineage, which is
        the only durable record of which fan-out that task closed
        (D102). Without one there is nothing to replay: the join has
        never fired, so its branches are still outstanding and the
        remedy is to rerun *them*, not the join.
        """

        fanout = None if last is None else _lineage_from(last)
        if fanout is None:
            raise Conflict(
                f"join {target.name!r} has not fired in run {run_id!r}; "
                "there are no arrivals to replay"
            )
        arrivals = await uow.joins.arrivals(run_id, target.name, fanout)
        if not arrivals:  # pragma: no cover - a fired join has its arrivals
            raise Conflict(
                f"join {target.name!r} has no stored arrivals in run {run_id!r}"
            )
        return arrivals_payload(arrivals), arrival_senders(arrivals), fanout

    async def _enqueue(
        self,
        uow: UnitOfWork,
        run_id: str,
        target: Node,
        payload: Any,
        *,
        reason: str,
        lineage: dict[str, Any],
        branch: Sequence[BranchFrame] = (),
        attempt: int = 1,
        from_task: int | None = None,
        arrivals: list[int] | None = None,
    ) -> TaskRow:
        """Enqueue one task at ``target`` and announce it.

        ``created`` is left to default to now: the two ops that must keep
        an older one — :meth:`retry` — pass it themselves.
        """

        priority, explicit = dispatch_key(target)
        task = await uow.tasks.enqueue(
            run_id,
            target.name,
            payload,
            priority,
            explicit,
            attempt=attempt,
            lineage=lineage,
            branch=branch,
        )
        uow.emit(
            _event(
                run_id,
                task.id,
                EventName.task_enqueued,
                TaskEnqueued(
                    node=target.name,
                    attempt=task.attempt,
                    reason=reason,  # pyright: ignore[reportArgumentType]
                    from_task=from_task,
                    payload_present=payload is not None,
                    branch=frame_summaries(branch),
                    arrivals=arrivals,
                ),
            )
        )
        return task

    async def _cancel_tasks(
        self, uow: UnitOfWork, run_id: str, *, reason: str
    ) -> list[int]:
        """Cancel every outstanding task of a run; return the ids."""

        cancelled: list[int] = []
        for task in await uow.tasks.list_for_run(run_id):
            if task.status.value not in PENDING:
                continue
            await self._cancel_task(uow, task, reason=reason)
            cancelled.append(task.id)
        return cancelled

    async def _cancel_task(
        self, uow: UnitOfWork, task: TaskRow, *, reason: str
    ) -> None:
        """Mark one task ``cancelled`` and say what cancelled it."""

        await uow.tasks.set_status(task.id, TaskStatus.cancelled.value)
        uow.emit(
            _event(
                task.run_id,
                task.id,
                EventName.task_cancelled,
                TaskCancelled(
                    node=task.node,
                    from_=task.status.value,
                    reason=reason,  # pyright: ignore[reportArgumentType]
                ),
            )
        )

    async def _reopen(self, uow: UnitOfWork, run: RunRow) -> None:
        """Put a terminal run back to ``running`` for the work just queued.

        03 §State machines has exactly three edges out of a terminal run
        — retry, rerun and move — and this is all three of them. The
        ``finished`` stamp is cleared with the status: a run that is
        going again has not finished, and leaving the timestamp would
        make every duration read from it wrong.
        """

        if run.status not in TERMINAL_RUNS:
            return
        await uow.runs.update(run.id, status=RunStatus.running.value, finished=None)
        uow.emit(
            _event(
                run.id,
                None,
                EventName.run_updated,
                RunUpdated(changed=RunChanges(status=RunStatus.running.value)),
            )
        )


def _clean_title(title: str) -> str:
    """A title with its surrounding whitespace gone, or a refusal."""

    clean = title.strip()
    if not clean:
        raise Conflict("a run needs a non-empty title")
    return clean


def _lineage_from(task: TaskRow) -> int | None:
    """``lineage.from`` as an int, or ``None`` when there is none."""

    lineage = task.lineage
    if not isinstance(lineage, dict):
        return None
    value = lineage.get(LINEAGE_FROM)
    return value if isinstance(value, int) else None


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
    "MANUAL_RETRY_REASON",
    "MOVE_REASON",
    "RERUN_REASON",
    "SET_STATUS_REASON",
    "START_REASON",
    "Ops",
    "OpsEngine",
    "SettableStatus",
]

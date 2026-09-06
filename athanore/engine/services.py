"""`TaskServices`: the narrow store surface a node body and a façade get.

04 §TaskContext. A body never touches :class:`~athanore.store.uow.Store`.
It reaches ``ctx.services``, and everything there is a verb the domain
has a name for — append a log entry, accept a submission, open a request,
read the run. That is what lets ``athanore.agents`` avoid importing
``athanore.store`` at all (02 §Layering) and what keeps user land from
writing a row the engine's invariants depend on.

Each service owns the transaction for its own verb, so the rule holds at
the only place it can: **one unit of work per state change, and the event
that describes it emitted inside it** (03 invariant 7). Nothing here spans
an await on a body, an agent, or a request wait — a `uow` block in this
module contains exactly its own writes.

:attr:`TaskServices.requests` is the one member that reaches a sibling
package. ``athanore.requests`` may not be imported from here (02
§Layering), so :class:`RequestsPort` is the contract a body's
``human_input`` is written against, :class:`RequestBackend` is the
contract the service on the other side satisfies, and
:class:`TaskRequests` is the object between them: the attempt's ids, the
``source`` a caller does not get to choose, and the ordinal that makes a
re-executed body re-attach to the question it already asked (06 §Restart
durability). An engine composed without a request service gets
:class:`UnwiredRequests` instead, whose every method raises — a port that
returned ``None`` or an empty answer would let ``human_input`` look like
it asked and silently take a default, which is the one failure mode a
human-in-the-loop feature cannot have.

:attr:`TaskServices.lease` is the one member the runner has to wire to
the attempt itself. :meth:`LeaseService.released` moves the task to
``waiting``, hands the lease back and re-acquires it from the pool's
re-admit queue (04 §Waiting), so it needs the context, the lease and the
scheduler's ``notify()`` — none of which a store gives it. It is
attached by the runner and refuses to release anything until it is: a
version that quietly did nothing would look like it worked, under
``workers=1``, right up to the first deadlock.

:attr:`TaskServices.stream` is the one member with a background task
behind it: chunks accumulate in memory and land as one insert per
``stream_flush_interval`` (07 §Transcript writes). The runner closes it in
the ``finally`` of every attempt, which is also its last flush.

:attr:`TaskServices.events` is the one member with a rule of its own. A
plugin or a body may publish, but only into the ``plugin.`` namespace:
the rest of the vocabulary describes state the engine owns, and a body
that could publish ``task.done`` could tell every SSE client and every
plugin subscriber that a task it is still running has finished.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager, suppress
from typing import TYPE_CHECKING, Any, Protocol, cast

from athanore.engine.pools import Lease, PoolState
from athanore.events.model import Event
from athanore.events.names import PLUGIN_PREFIX, EventName, is_known
from athanore.events.payloads import (
    LogAppended,
    SubmissionAccepted,
    SubmissionRejected,
    TaskResumed,
    TaskStream,
    TaskWaiting,
    ValidationError,
)
from athanore.logging import get_logger
from athanore.store.clock import now
from athanore.store.rows import (
    AnswerAuthor,
    AnswerRow,
    ChunkKind,
    LogAuthor,
    LogEntryRow,
    LogKind,
    RequestKind,
    RequestMode,
    RequestRow,
    RequestSource,
    RunRow,
    SubmissionRow,
    TaskStatus,
)
from athanore.store.uow import Store

if TYPE_CHECKING:  # `context` imports this module: the arrow points one way.
    from athanore.engine.context import TaskContext

#: How much of an entry ``log.appended`` carries (18 §Log and stats). The
#: rest is fetched by id: an event never carries full log text.
PREVIEW_CHARS = 200

_log = get_logger(__name__)


class LogService:
    """The work log of one attempt (03 §LogEntry).

    Append-only, like the repository under it. ``author`` defaults to
    ``agent`` because the overwhelming majority of entries are written
    through ``POST /api/agent/tasks/{id}/log`` by the agent running the
    node; the engine and the operator name themselves.
    """

    def __init__(self, store: Store, *, run_id: str, task_id: int, node: str) -> None:
        self._store = store
        self._run_id = run_id
        self._task_id = task_id
        self._node = node

    async def append(
        self,
        text: str,
        *,
        author: LogAuthor | str = LogAuthor.agent,
        kind: LogKind | str | None = None,
    ) -> LogEntryRow:
        """Add one entry to the run's work log and announce it.

        One transaction: the row and its ``log.appended``. The event
        carries the first :data:`PREVIEW_CHARS` characters and the id;
        a reader that wants the entry fetches it (18 §Rules).

        ``author`` and ``kind`` are coerced through the domain enums, so a
        misspelling is a ``ValueError`` here rather than a row nothing
        will ever filter on.
        """
        entry_author = LogAuthor(author)
        entry_kind = None if kind is None else LogKind(kind)
        async with self._store.uow() as uow:
            row = await uow.log.append(
                run_id=self._run_id,
                node=self._node,
                author=entry_author,
                text=text,
                task_id=self._task_id,
                kind=entry_kind,
            )
            uow.emit(
                Event(
                    run_id=self._run_id,
                    task_id=self._task_id,
                    name=EventName.log_appended,
                    data=LogAppended(
                        log_id=row.id,
                        author=str(entry_author),
                        node=self._node,
                        kind=None if entry_kind is None else str(entry_kind),
                        preview=text[:PREVIEW_CHARS],
                    ).model_dump(),
                    created=now(),
                )
            )
        return row


class StreamService:
    """The agent transcript of one attempt, written in batches.

    07 §Transcript writes. An agent turn produces chunks faster than a
    database wants statements — a token at a time, a tool call at a time —
    so the façade appends into memory here and a background flusher writes
    what has accumulated every ``stream_flush_interval`` as **one**
    multi-row insert, followed by one ephemeral ``task.stream`` naming the
    range it wrote. Two to three flushes a second per streaming task is
    also why that event is never stored: it would be most of the ``events``
    table, and a late joiner rebuilds the transcript from
    ``GET /api/tasks/{id}/stream?after=`` instead (03, ``EPHEMERAL``).

    ``seq`` is the cursor that endpoint pages by, and it is unique per
    task, so the counter is initialised from
    :meth:`~athanore.store.repos.stream.StreamRepo.last_seq` rather than
    from zero: an attempt that is re-executed after a crash (04
    §Durability) writes chunk ``n+1``, not chunk ``1`` again against rows
    that are already there. The read happens on the first
    :meth:`append` — the only moment at which it is both needed and
    cheap — which is what lets the service be constructed synchronously
    beside the others and still be correct.

    **Nothing here reaches the body.** A failed flush is logged and the
    buffer is left alone, so the next tick retries it; the transcript is
    diagnostic (the work log carries the deliverables), and an agent turn
    that failed because a batch insert did is a worse outcome than a turn
    with a gap in its transcript. The one thing that must not happen is
    writing a batch twice, so the buffer is trimmed only after the
    transaction has committed, and :meth:`close` waits out an in-flight
    flush before it cancels the flusher.
    """

    def __init__(
        self,
        store: Store,
        *,
        run_id: str,
        task_id: int,
        flush_interval: float,
    ) -> None:
        self._store = store
        self._run_id = run_id
        self._task_id = task_id
        self._interval = flush_interval
        #: Chunks written but not yet inserted, oldest first.
        self.buffer: list[tuple[int, str, str]] = []
        #: The highest ``seq`` handed out, or ``None`` before the first read.
        self._seq: int | None = None
        self._flusher: asyncio.Task[None] | None = None
        self._flushing = asyncio.Lock()
        self._closed = False

    async def append(self, kind: ChunkKind | str, text: str) -> int:
        """Buffer one chunk and return the ``seq`` it was given.

        A coroutine rather than a plain call because the first chunk of an
        attempt is what resolves the counter against the store; every
        chunk after it appends and returns without awaiting anything. The
        flusher is started here too, so a body that never streams never
        has a background task.
        """
        if self._closed:
            raise RuntimeError(
                f"the transcript of task {self._task_id} is closed; "
                "the attempt has ended"
            )
        chunk_kind = ChunkKind(kind)
        if self._seq is None:
            async with self._store.reader() as reader:
                self._seq = await reader.stream.last_seq(self._task_id)
        self._seq += 1
        self.buffer.append((self._seq, str(chunk_kind), text))
        if self._flusher is None:
            self._flusher = asyncio.get_running_loop().create_task(self._flusher_loop())
        return self._seq

    async def close(self) -> None:
        """Stop the flusher and write what is left. Idempotent.

        The last chunks of a finished agent turn are the ones a reader
        most wants, so the flusher is not simply cancelled: an in-flight
        flush is waited out under :attr:`_flushing` first, which is what
        makes cancelling it impossible in the window where a cancellation
        could leave a committed batch still in the buffer — and therefore
        written twice, against a unique ``seq``.
        """
        if self._closed:
            return
        self._closed = True
        flusher, self._flusher = self._flusher, None
        if flusher is not None:
            async with self._flushing:
                # Held across the cancel, and no await between: the flusher
                # is either sleeping or waiting for this lock, never mid-write.
                flusher.cancel()
            with suppress(asyncio.CancelledError):
                await flusher
        await self._flush_guarded()

    async def _flusher_loop(self) -> None:
        """Flush every ``flush_interval`` until cancelled."""
        while True:
            await asyncio.sleep(self._interval)
            await self._flush_guarded()

    async def _flush_guarded(self) -> None:
        """One flush, with its failures logged rather than raised.

        Retries are the engine's (rule 3) and this is not the engine: a
        flush that failed is retried on the next tick because the buffer
        still holds its chunks, and an attempt is never failed by its own
        transcript.
        """
        async with self._flushing:
            try:
                await self._flush()
            except Exception:
                _log.warning(
                    "stream flush failed",
                    task_id=self._task_id,
                    buffered=len(self.buffer),
                    exc_info=True,
                )

    async def _flush(self) -> None:
        """Write the buffer as one batch and announce the range.

        The buffered prefix that was written is dropped only after the
        transaction has committed, so a failure leaves the chunks to be
        retried and a chunk appended while the insert was in flight is
        kept for the next batch.
        """
        batch = list(self.buffer)
        if not batch:
            return
        async with self._store.uow() as uow:
            await uow.stream.append_batch(self._task_id, batch)
        del self.buffer[: len(batch)]
        await self._store.publish_ephemeral(
            Event(
                run_id=self._run_id,
                task_id=self._task_id,
                name=EventName.task_stream,
                data=TaskStream(seq_from=batch[0][0], seq_to=batch[-1][0]).model_dump(),
                created=now(),
            )
        )


class SubmissionService:
    """The values an agent submitted for this attempt (03 §Submission).

    A submission never routes anything — the body reads
    :meth:`latest` and decides — so there is nothing here but recording
    one and announcing it.
    """

    def __init__(self, store: Store, *, run_id: str, task_id: int, node: str) -> None:
        self._store = store
        self._run_id = run_id
        self._task_id = task_id
        self._node = node

    async def latest(self) -> SubmissionRow | None:
        """The newest submission of this attempt, or ``None``.

        A read, so it takes a pooled connection and no writer lock: a body
        polling for a submission must not queue behind a commit.
        """
        async with self._store.reader() as reader:
            return await reader.submissions.latest(self._task_id)

    async def accept(self, payload: Any) -> SubmissionRow:
        """Record a payload that passed the declared model.

        One transaction: the row and ``submission.accepted``. Only
        validated payloads reach here (the endpoint validates against
        ``ctx.output_model`` first, T045), which is what makes
        :meth:`latest` safe for a body to trust.
        """
        async with self._store.uow() as uow:
            row = await uow.submissions.insert(self._task_id, payload)
            uow.emit(
                Event(
                    run_id=self._run_id,
                    task_id=self._task_id,
                    name=EventName.submission_accepted,
                    data=SubmissionAccepted(
                        node=self._node, submission_id=row.id
                    ).model_dump(),
                    created=now(),
                )
            )
        return row

    async def reject(
        self,
        errors: Sequence[Mapping[str, Any]],
        schema: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Announce a submission that did not fit, storing no row.

        A rejected payload is not a submission: storing it would make
        :meth:`latest` return something the body must not act on. The
        event is the whole record.

        The returned ``{"errors": …, "schema": …}`` is what the endpoint
        answers 422 with and what it records as ``ctx.last_rejection`` for
        the repair prompt (T035, T045), so the errors an agent is shown
        and the errors the operator sees are the same object.
        """
        reported = [_validation_error(error) for error in errors]
        async with self._store.uow() as uow:
            uow.emit(
                Event(
                    run_id=self._run_id,
                    task_id=self._task_id,
                    name=EventName.submission_rejected,
                    data=SubmissionRejected(
                        node=self._node, errors=reported
                    ).model_dump(),
                    created=now(),
                )
            )
        return {
            "errors": [error.model_dump() for error in reported],
            "schema": dict(schema),
        }


class RunService:
    """The run this attempt belongs to (03 §Run)."""

    def __init__(self, store: Store, *, run_id: str) -> None:
        self._store = store
        self._run_id = run_id

    async def get(self) -> RunRow:
        """The run row, freshly read.

        Raises ``RuntimeError`` if it is gone: a run is deleted only by
        ``ops.delete``, which cancels every task under it first (04
        §Operator operations), so a body that cannot find its run is
        looking at a bug, not at an ordinary race.
        """
        async with self._store.reader() as reader:
            row = await reader.runs.get(self._run_id)
        if row is None:
            raise RuntimeError(f"run {self._run_id!r} no longer exists")
        return row


class LeaseService:
    """The attempt's slot in its pool (04 §Pools, §Waiting).

    A body that parks on a human gives its lease back so another task can
    run, and takes one again through the pool's re-admit queue when the
    answer arrives. That pair is :meth:`released`, and it is the whole of
    what makes a one-worker install usable: the MVP held the slot through
    the wait, so under ``workers=1`` one playtest question stalled the
    whole server.

    The service is constructed with the attempt's ids and wired by the
    runner through :meth:`attach`, which hands it the three things only
    the runner has — the :class:`~athanore.engine.context.TaskContext` the
    body runs under, the :class:`~athanore.engine.pools.Lease` the
    scheduler took for it, and the engine's ``notify()``. Until then
    :meth:`released` refuses rather than doing nothing: a body waiting
    outside a dispatched attempt has no slot to give back and no loop to
    give it to.

    :attr:`held` is the lease the attempt holds **now** — the one the
    scheduler handed over, or the one the re-admit queue gave it after a
    wait. The runner's ``finally`` releases that one through
    :meth:`release`, and it is the only thing that ever does: the second
    lease of a resumed body is a different object, and the scheduler's
    reap only knows the first.
    """

    def __init__(
        self,
        store: Store,
        *,
        run_id: str,
        task_id: int,
        node: str,
    ) -> None:
        self._store = store
        self._run_id = run_id
        self._task_id = task_id
        self._node = node
        self._context: TaskContext | None = None
        self._lease: Lease | None = None
        self._notify: Callable[[], None] | None = None
        self._waiting = False

    # -- wiring ------------------------------------------------------------

    def attach(
        self, context: TaskContext, lease: Lease, notify: Callable[[], None]
    ) -> None:
        """Wire the service to the attempt the runner is about to run.

        Called once, after the context is built and before the body is
        entered (04 §Running an attempt). Attaching twice is a defect
        rather than a rebind: two contexts sharing one services bundle
        would leave ``released()`` writing the other attempt's status.
        """
        if self._context is not None:
            raise RuntimeError(
                f"the lease service of task {self._task_id} is already attached "
                "to an attempt"
            )
        self._context = context
        self._lease = lease
        self._notify = notify

    @property
    def held(self) -> Lease | None:
        """The lease this attempt holds now, or ``None`` before it is wired.

        Not the lease it started with: after a wait it is the one the
        re-admit queue handed over.
        """
        return self._lease

    @property
    def waiting(self) -> bool:
        """Whether the body is inside :meth:`released` right now."""
        return self._waiting

    def release(self) -> None:
        """Give the slot this attempt holds back to its pool. Idempotent.

        The runner's ``finally`` calls it on every path, so a body that
        resumed and then failed returns the lease it actually holds
        rather than the one it was dispatched with.
        """
        if self._lease is not None:
            self._lease.release()

    # -- waiting -----------------------------------------------------------

    @asynccontextmanager
    async def released(self, request_id: int) -> AsyncGenerator[None]:
        """Give the slot back for the duration of the block (04 §Waiting).

        ``request_id`` is the request the body is about to wait on: it is
        the payload of both events, and the pair of them is what tells an
        operator which question a task is parked on.

        On the way in, in this order: one transaction moves the task to
        ``waiting`` and emits ``task.waiting``; the node timeout is
        paused; the lease goes back; the scheduler is woken. The status is
        durable *before* the slot is free, so a task that another attempt
        starts against cannot find this one still ``in_progress``.

        On the way out the task joins its pool's re-admit queue and waits
        there for a lease — ahead of every ``ready`` task in the pool, and
        behind every body answered before it (04 §Waiting). It stays
        ``waiting`` while it queues and flips to ``in_progress``
        (``task.resumed``) when the lease is handed over, which is what
        makes "queued for a slot" visible rather than indistinguishable
        from "running".

        The node timeout is **paused**, not merely restored: the scope is
        disarmed on the way in and re-armed on the way out with the time
        that was left when the body parked. A node with ``timeout=300``
        that waits an hour for a human would otherwise be cancelled inside
        the wait, and one that survived it would fail the moment it
        resumed (D108).

        Cancellation is the one exit that does not re-acquire. An operator
        cancelling the task, or a shutdown, leaves nothing to run: there
        is no slot to take back, and no status to write (D52) — recovery
        turns a ``waiting`` row back into ``ready``.
        """
        context, lease, notify = self._attached()
        if self._waiting:
            raise RuntimeError(
                f"task {self._task_id} is already waiting: released() is the "
                "body's one park, and a second one would release a slot the "
                "attempt no longer holds"
            )
        pool = lease.pool_state
        loop = asyncio.get_running_loop()
        deadline = _deadline(context)

        async with self._store.uow() as uow:
            await uow.tasks.set_status(self._task_id, TaskStatus.waiting)
            uow.emit(
                Event(
                    run_id=self._run_id,
                    task_id=self._task_id,
                    name=EventName.task_waiting,
                    data=TaskWaiting(
                        node=self._node, request_id=request_id
                    ).model_dump(),
                    created=now(),
                )
            )
        released_at = loop.time()
        context._released_at = released_at  # pyright: ignore[reportPrivateUsage]
        if deadline is not None:
            _timeout_of(context).reschedule(None)
        self._waiting = True
        lease.release()
        notify()

        try:
            try:
                yield
            finally:
                # The park is over however it ended; only what happens next
                # depends on how.
                self._waiting = False
        except asyncio.CancelledError:
            # An operator op or a shutdown. There is nothing left to run,
            # so there is no slot to take back and no status to write
            # (D52): recovery turns the `waiting` row back into `ready`.
            raise
        except BaseException:
            # A wait that timed out, or a body that raised inside the
            # block. The attempt goes on to record an outcome, and the
            # runner records that as a running task: it needs its slot.
            await self._resume(
                context,
                request_id,
                pool=pool,
                notify=notify,
                deadline=deadline,
                released_at=released_at,
            )
            raise
        await self._resume(
            context,
            request_id,
            pool=pool,
            notify=notify,
            deadline=deadline,
            released_at=released_at,
        )

    async def _resume(
        self,
        context: TaskContext,
        request_id: int,
        *,
        pool: PoolState,
        notify: Callable[[], None],
        deadline: float | None,
        released_at: float,
    ) -> None:
        """Queue for a slot, take it, and put the task back in progress."""
        lease = await _take_readmit(pool, self._task_id, notify)
        self._lease = lease
        loop = asyncio.get_running_loop()

        async with self._store.uow() as uow:
            await uow.tasks.set_status(self._task_id, TaskStatus.in_progress)
            uow.emit(
                Event(
                    run_id=self._run_id,
                    task_id=self._task_id,
                    name=EventName.task_resumed,
                    data=TaskResumed(
                        node=self._node,
                        request_id=request_id,
                        waited_s=loop.time() - released_at,
                    ).model_dump(),
                    created=now(),
                )
            )
        if deadline is not None:
            # What was left of the node's budget when it parked, from now.
            _timeout_of(context).reschedule(loop.time() + (deadline - released_at))
        context._released_at = None  # pyright: ignore[reportPrivateUsage]

    def _attached(self) -> tuple[TaskContext, Lease, Callable[[], None]]:
        """The runner's three, or a ``RuntimeError`` naming what is missing."""
        context, lease, notify = self._context, self._lease, self._notify
        if context is None or lease is None or notify is None:
            raise RuntimeError(
                f"task {self._task_id} has no pool lease: released() releases "
                "the slot of a dispatched attempt, and this services bundle "
                "was never attached to one"
            )
        return context, lease, notify


async def _take_readmit(
    pool: PoolState, task_id: int, notify: Callable[[], None]
) -> Lease:
    """Join ``pool``'s re-admit queue and wait for the lease it hands over.

    The place in the queue is taken by the call, not by the await, so two
    bodies answered in order re-enter in that order. The scheduler serves
    the queue at the top of a tick, so it is woken here too: with a free
    slot and nothing else to dispatch, the alternative is a body that
    waits out a whole tick after its answer has already arrived.

    A lease handed to a waiter that is then cancelled is given back rather
    than dropped. The queue spent a slot on it and nothing else holds a
    reference to it — under ``workers=1`` losing it is the engine wedged
    until a restart.
    """
    readmit = pool.request_readmit(task_id)
    notify()
    try:
        return await readmit
    except BaseException:
        if readmit.done() and not readmit.cancelled() and not readmit.exception():
            readmit.result().release()
        raise


def _timeout_of(context: TaskContext) -> asyncio.Timeout:
    """The runner's timeout scope for this attempt.

    Only called where :func:`_deadline` already answered with a deadline,
    so the scope is there; the check is what keeps that from being an
    assumption two call sites down.
    """
    scope = context._timeout  # pyright: ignore[reportPrivateUsage]
    if scope is None:  # pragma: no cover - guarded by `_deadline`
        raise RuntimeError(f"task {context.task_id} has no timeout scope")
    return scope


def _deadline(context: TaskContext) -> float | None:
    """When the node timeout fires, or ``None`` if the node has none.

    ``asyncio.timeout(None)`` is a scope with no deadline, which is what a
    node without a ``timeout`` runs under, so "there is a scope" and
    "there is a clock to pause" are two questions (04 §Timeouts).
    """
    scope = context._timeout  # pyright: ignore[reportPrivateUsage]
    return None if scope is None else scope.when()


class EventPort:
    """Publishing into the ``plugin.`` namespace, and nowhere else.

    18 §Plugins: ``plugin.<workflow>.<name>`` carries whatever the handler
    passed, and ``data`` must be a JSON object. Everything else in the
    vocabulary describes state the engine owns and is emitted by the
    transaction that changed it (03 invariant 7), so user land publishing
    one would be a claim about state, made by something that did not
    change any — an SSE client told a task is done while its body is still
    running, a plugin subscriber acting on a run that never completed.
    """

    def __init__(
        self, store: Store, *, run_id: str, task_id: int, workflow: str
    ) -> None:
        self._store = store
        self._run_id = run_id
        self._task_id = task_id
        self._workflow = workflow

    async def publish(self, name: str, data: Mapping[str, Any]) -> Event:
        """Store and publish ``plugin.<workflow>.<name>``.

        Raises ``ValueError`` for any other name, for a name outside this
        workflow's namespace, and ``TypeError`` for a ``data`` that is not
        a mapping.
        """
        self._check(name)
        event = Event(
            run_id=self._run_id,
            task_id=self._task_id,
            name=name,
            data=_json_object(name, data),
            created=now(),
        )
        async with self._store.uow() as uow:
            uow.emit(event)
        return event

    def _check(self, name: str) -> None:
        """Refuse anything that is not this workflow's plugin namespace."""
        if not name.startswith(PLUGIN_PREFIX) or not is_known(name):
            raise ValueError(
                f"{name!r} is not a plugin event: publish is restricted to "
                f"{PLUGIN_PREFIX}<workflow>.<name> with identifier segments, "
                "because the rest of the vocabulary is the engine's to emit"
            )
        workflow = name.split(".")[1]
        if workflow != self._workflow:
            raise ValueError(
                f"{name!r} names workflow {workflow!r}, but this task belongs "
                f"to {self._workflow!r}; a workflow publishes only in its own "
                "namespace (18 §Plugins)"
            )


#: What a ``form`` request's waiter registers to have its answer checked
#: where it lands: a callable that takes the answer as it arrived and
#: returns the value to store, or raises (06 §Service). Spelled
#: structurally rather than imported —
#: ``athanore.requests.validators.Validator`` is the same type, and
#: ``athanore.requests`` is this package's independent sibling (02
#: §Layering).
AnswerValidator = Callable[[Any], Any]


class RequestsPort(Protocol):
    """What ``human_input`` and the agent bridge need of the request layer.

    Named here as a protocol because ``athanore.requests`` is an
    independent sibling of ``athanore.engine`` in the middle tier (02
    §Layering): the engine states the shape it hands a body, and
    :class:`TaskRequests` is the object that satisfies it, built and
    wired per attempt by the runner.

    ``reopen_or_create`` is the one with a rule attached. It takes the
    next ``ctx.request_ordinal`` and re-attaches to the request already
    open at that ordinal if there is one, which is what makes a body
    re-executed after a crash ask question three rather than questions one
    through three again (06 §Restart durability).
    """

    async def reopen_or_create(
        self,
        prompt: str,
        *,
        mode: RequestMode,
        kind: RequestKind,
        options: list[dict[str, Any]] | None = None,
        schema: dict[str, Any] | None = None,
    ) -> RequestRow: ...

    async def create_agent_request(
        self,
        prompt: str,
        *,
        mode: RequestMode,
        kind: RequestKind,
        options: list[dict[str, Any]] | None = None,
        schema: dict[str, Any] | None = None,
        tool_call: dict[str, Any] | None = None,
    ) -> RequestRow: ...

    async def answer_as_engine(
        self, request_id: int, option_id: str | None = None
    ) -> AnswerRow: ...

    def register_validator(self, request_id: int, fn: AnswerValidator) -> None:
        """Validate this request's ``form`` answer with ``fn`` when it lands.

        Registered by whoever opened the request, because only they know
        what the answer is for (06 §Service): ``human_input(output_model=M)``
        registers a validator built from ``M``, and the ACP bridge one
        built from the schema the agent sent. Validation happens where the
        answer lands, so a misfit is refused to the face that gave it
        rather than in a node body several seconds later.
        """
        ...

    def unregister_validator(self, request_id: int) -> None:
        """Forget this request's validator. Not having one is not an error.

        Called by the waiter on its way out, answered or not: a validator
        left behind would validate the next answer to a request nobody is
        waiting on any more.
        """
        ...

    # ASYNC109: `timeout` is 06 §Service's signature, and the seconds are
    # what the implementation hands to `asyncio.timeout` (T031) rather than a
    # hand-rolled clock; a caller cannot wrap this in one, because the wait
    # has to be cancelled *and* the request left pending for the next waiter.
    async def wait(
        self,
        request_id: int,
        timeout: float | None = None,  # noqa: ASYNC109
    ) -> AnswerRow: ...

    async def poll(self, request_id: int, wait_s: float) -> AnswerRow | None: ...


class UnwiredRequests:
    """The :class:`RequestsPort` of an engine with no request service.

    Every method raises. The alternative — a port that returned ``None``
    or an empty answer — would let ``human_input`` look like it asked and
    silently take a default, which is the one failure mode a human-in-the-
    loop feature cannot have.

    An engine reaches this only when it was composed without a
    :class:`RequestBackend`: the engine cannot construct one for itself
    (02 §Layering), so the composition root passes it in, and one that
    did not gets a channel that says so on first use rather than a
    workflow that quietly never asks anybody anything.
    """

    _MESSAGE = (
        "this engine has no request service: TaskServices.requests is "
        "unwired, so nothing can open or answer a request on it "
        "(Engine(..., requests=RequestService(store, bus)), 06 §Service)"
    )

    async def reopen_or_create(
        self,
        prompt: str,
        *,
        mode: RequestMode,
        kind: RequestKind,
        options: list[dict[str, Any]] | None = None,
        schema: dict[str, Any] | None = None,
    ) -> RequestRow:
        raise NotImplementedError(self._MESSAGE)

    async def create_agent_request(
        self,
        prompt: str,
        *,
        mode: RequestMode,
        kind: RequestKind,
        options: list[dict[str, Any]] | None = None,
        schema: dict[str, Any] | None = None,
        tool_call: dict[str, Any] | None = None,
    ) -> RequestRow:
        raise NotImplementedError(self._MESSAGE)

    async def answer_as_engine(
        self, request_id: int, option_id: str | None = None
    ) -> AnswerRow:
        raise NotImplementedError(self._MESSAGE)

    def register_validator(self, request_id: int, fn: AnswerValidator) -> None:
        raise NotImplementedError(self._MESSAGE)

    def unregister_validator(self, request_id: int) -> None:
        raise NotImplementedError(self._MESSAGE)

    async def wait(
        self,
        request_id: int,
        timeout: float | None = None,  # noqa: ASYNC109 - the port's signature
    ) -> AnswerRow:
        raise NotImplementedError(self._MESSAGE)

    async def poll(self, request_id: int, wait_s: float) -> AnswerRow | None:
        raise NotImplementedError(self._MESSAGE)


class RequestBackend(Protocol):
    """What :class:`TaskRequests` needs of the request service (06 §Service).

    A structural protocol for the reason
    :class:`~athanore.engine.runner.RunnerEngine` is one:
    ``athanore.requests`` is an **independent sibling** of
    ``athanore.engine`` in the middle tier (02 §Layering), so neither
    package may import the other. The engine states the shape it delegates
    to, ``athanore.requests.service.RequestService`` satisfies it without
    knowing that the engine exists, and the composition root — the server
    host, or a test — is what puts the two together.

    Every method here is 06 §Service's, unchanged: this port adds the
    ordinal and the task's identity, and no service logic of its own.
    """

    async def create(
        self,
        run_id: str,
        task_id: int,
        prompt: str,
        *,
        mode: RequestMode,
        source: RequestSource,
        kind: RequestKind,
        options: list[dict[str, Any]] | None = None,
        schema: dict[str, Any] | None = None,
        tool_call: dict[str, Any] | None = None,
        ordinal: int | None = None,
    ) -> RequestRow: ...

    async def reopen(self, task_id: int, ordinal: int) -> RequestRow | None: ...

    def register_validator(self, request_id: int, fn: AnswerValidator) -> None: ...

    def unregister_validator(self, request_id: int) -> None: ...

    async def answer(
        self,
        request_id: int,
        *,
        option_id: str | None = None,
        value: Any = None,
        author: AnswerAuthor = AnswerAuthor.user,
    ) -> AnswerRow: ...

    # ASYNC109: the port's signature, for the reason `RequestsPort` gives.
    async def wait(
        self,
        request_id: int,
        timeout: float | None = None,  # noqa: ASYNC109
    ) -> AnswerRow: ...

    async def poll(self, request_id: int, wait_s: float) -> AnswerRow | None: ...


class TaskRequests:
    """One task's view of the request channel: the :class:`RequestsPort`.

    Constructed per attempt over the one process-wide
    :class:`RequestBackend`, and wired to the attempt by :meth:`attach`
    for the same reason :class:`LeaseService` is: the counter it keeps is
    the *context's*, and the context does not exist yet when the services
    bundle is built.

    The whole of the class is the ordinal. ``run_id`` and ``task_id`` come
    from the attempt rather than from the caller, so a body cannot open a
    request against another task; ``source`` is decided by which method was
    called rather than passed, so a body cannot open a request that claims
    an agent raised it; and :meth:`reopen_or_create` numbers the
    node-raised ones so that a body re-executed after a crash asks question
    three rather than questions one through three again (06 §Restart
    durability).

    :meth:`create_agent_request` deliberately has no ordinal. An agent's
    permission prompts arrive from inside a turn that a re-execution does
    not reproduce statement for statement — the model may stop asking, or
    ask something else — so numbering them by position would replay one
    answer onto a different question. The whole attempt re-runs and its
    agent-raised requests stay in history as stale (06 §Restart
    durability).
    """

    def __init__(self, service: RequestBackend, *, run_id: str, task_id: int) -> None:
        self._service = service
        self._run_id = run_id
        self._task_id = task_id
        self._context: TaskContext | None = None

    # -- wiring ------------------------------------------------------------

    def attach(self, context: TaskContext) -> None:
        """Wire the port to the attempt whose ordinals it counts.

        Called by the runner once, beside :meth:`LeaseService.attach` and
        for the same reason. Attaching twice is a defect rather than a
        rebind: two contexts sharing one port would have the second
        attempt's questions numbered from the first attempt's counter.
        """
        if self._context is not None:
            raise RuntimeError(
                f"the requests port of task {self._task_id} is already "
                "attached to an attempt"
            )
        self._context = context

    # -- opening -----------------------------------------------------------

    async def reopen_or_create(
        self,
        prompt: str,
        *,
        mode: RequestMode,
        kind: RequestKind,
        options: list[dict[str, Any]] | None = None,
        schema: dict[str, Any] | None = None,
    ) -> RequestRow:
        """The request this body asks at its next ordinal, opening one if new.

        Three lines and a rule (06 §Restart durability). The counter on
        the context moves first, so this call *owns* position *n* whatever
        happens next; the store is asked what is at position *n* on this
        task row; and only a gap there is a question that has not been
        asked yet.

        An existing request is returned whether or not it has an answer,
        because both cases are the caller's to decide: answered, the
        answer replays (T033a re-validates it); pending, the body parks on
        the question it already asked. A crash mid-wait therefore costs
        the operator nothing — the same question, with the answer they may
        already have given still attached to it.

        A retry or a rerun is a *new task row*, so its ordinals start at 1
        and it asks afresh: the answers of a failed attempt may have been
        the reason it failed.
        """
        context = self._attached()
        ordinal = context.request_ordinal + 1
        context.request_ordinal = ordinal
        existing = await self._service.reopen(self._task_id, ordinal)
        if existing is not None:
            return existing
        return await self._service.create(
            self._run_id,
            self._task_id,
            prompt,
            mode=mode,
            source=RequestSource.node,
            kind=kind,
            options=options,
            schema=schema,
            ordinal=ordinal,
        )

    async def create_agent_request(
        self,
        prompt: str,
        *,
        mode: RequestMode,
        kind: RequestKind,
        options: list[dict[str, Any]] | None = None,
        schema: dict[str, Any] | None = None,
        tool_call: dict[str, Any] | None = None,
    ) -> RequestRow:
        """Open a request the agent raised mid-turn: a permission, an
        elicitation, or an HTTP ask.

        ``source="agent"`` and no ordinal, for the reason in the class
        docstring. ``tool_call`` is the ACP tool call a permission is
        about, carried so the SPA can show what is being asked for (06
        §The model).

        No context is needed: this is the one opening that does not count.
        """
        return await self._service.create(
            self._run_id,
            self._task_id,
            prompt,
            mode=mode,
            source=RequestSource.agent,
            kind=kind,
            options=options,
            schema=schema,
            tool_call=tool_call,
        )

    # -- answering and waiting ---------------------------------------------

    async def answer_as_engine(
        self, request_id: int, option_id: str | None = None
    ) -> AnswerRow:
        """Record the headless fallback's answer (05 §Policies, 06 §Timeouts).

        ``author="engine"``, which is what makes an answer nobody gave
        legible as one afterwards: a permission that timed out into its
        ``permission_timeout_action``, or an elicitation declined past the
        timeout. The refusals are :meth:`RequestBackend.answer`'s — an
        engine answer to a request a person answered first is
        :exc:`~athanore.requests.errors.AlreadyAnswered`, and the person's
        answer stands.
        """
        return await self._service.answer(
            request_id, option_id=option_id, author=AnswerAuthor.engine
        )

    def register_validator(self, request_id: int, fn: AnswerValidator) -> None:
        """Register ``fn`` as this request's answer validator (06 §Service).

        Straight to the service, which is where the answer lands and so
        where the validator has to be. The pair is the body's to manage —
        ``human_input`` registers before it parks and unregisters in a
        ``finally`` — because the body is the waiter, and the validator is
        the shape *it* asked for.
        """
        self._service.register_validator(request_id, fn)

    def unregister_validator(self, request_id: int) -> None:
        """Forget this request's validator. Idempotent, like the service's."""
        self._service.unregister_validator(request_id)

    async def wait(
        self,
        request_id: int,
        timeout: float | None = None,  # noqa: ASYNC109 - the port's signature
    ) -> AnswerRow:
        """Block until ``request_id`` is answered, and claim the answer.

        Straight to the service. The slot the body is holding while it
        waits is not this object's business: ``human_input`` wraps the
        wait in ``ctx.services.lease.released(request_id)``, and that pair
        is what 04 §Waiting specifies.
        """
        return await self._service.wait(request_id, timeout)

    async def poll(self, request_id: int, wait_s: float) -> AnswerRow | None:
        """The answer, waiting up to ``wait_s``; ``None`` if none came.

        The agent long-poll (08 §Agent). Claims nothing, so a reconnecting
        agent that asks twice gets the same answer twice.
        """
        return await self._service.poll(request_id, wait_s)

    # -- internals ---------------------------------------------------------

    def _attached(self) -> TaskContext:
        """The attempt this port counts ordinals in, or a refusal.

        Refuses rather than counting from zero: a port with no context is
        one nothing wired, and numbering a question from a counter that
        restarts every call would re-attach a body to its *first* request
        forever.
        """
        if self._context is None:
            raise RuntimeError(
                f"the requests port of task {self._task_id} is not attached "
                "to an attempt: a node-raised request is numbered by "
                "`ctx.request_ordinal`, and there is no context to number "
                "it in"
            )
        return self._context


class TaskServices:
    """The bundle hanging off :attr:`TaskContext.services`.

    Constructed by the runner once per attempt and handed to the body
    through the context. Each member is scoped to this attempt: the log
    entries it appends belong to this run and this node, the submissions
    it reads are this task's, the events it publishes carry this task's
    id. Nothing here takes an id from the caller, which is what stops one
    body from writing into another's run.
    """

    def __init__(
        self,
        store: Store,
        *,
        run_id: str,
        task_id: int,
        node: str,
        workflow: str,
        flush_interval: float,
        requests: RequestsPort | None = None,
    ) -> None:
        self.log = LogService(store, run_id=run_id, task_id=task_id, node=node)
        self.stream = StreamService(
            store, run_id=run_id, task_id=task_id, flush_interval=flush_interval
        )
        self.submissions = SubmissionService(
            store, run_id=run_id, task_id=task_id, node=node
        )
        self.requests: RequestsPort = (
            UnwiredRequests() if requests is None else requests
        )
        self.run = RunService(store, run_id=run_id)
        self.lease = LeaseService(store, run_id=run_id, task_id=task_id, node=node)
        self.events = EventPort(
            store, run_id=run_id, task_id=task_id, workflow=workflow
        )


def _json_object(name: str, data: object) -> dict[str, Any]:
    """``data`` as a plain dict, or a ``TypeError`` naming what it was.

    18 §Plugins requires a JSON object. The parameter is ``object`` rather
    than a mapping because this is where a *typed* signature stops being
    the check: the caller is user land, and a list reaching the store as
    an event payload is a row no consumer of the vocabulary can read.
    """
    if not isinstance(data, Mapping):
        raise TypeError(
            f"the data of {name!r} must be a JSON object, got {type(data).__name__}"
        )
    return dict(cast("Mapping[str, Any]", data))


def _validation_error(error: Mapping[str, Any]) -> ValidationError:
    """One pydantic error projected onto 18's three fields.

    ``ValidationError.errors()`` carries ``input``, ``url`` and sometimes
    ``ctx`` beside them; ``loc``, ``msg`` and ``type`` are what 18 fixes,
    and an event payload refuses what it does not name. The input value is
    dropped rather than forwarded — it is the payload an agent submitted
    and may be large or sensitive (18 §Rules).
    """
    missing = [key for key in ("loc", "msg", "type") if key not in error]
    if missing:
        raise ValueError(
            f"a validation error must carry loc, msg and type; "
            f"{', '.join(missing)} missing from {sorted(error)}"
        )
    return ValidationError(
        loc=list(error["loc"]),
        msg=str(error["msg"]),
        type=str(error["type"]),
    )


__all__ = [
    "PREVIEW_CHARS",
    "EventPort",
    "LeaseService",
    "LogService",
    "RequestBackend",
    "RequestsPort",
    "RunService",
    "StreamService",
    "SubmissionService",
    "TaskRequests",
    "TaskServices",
    "UnwiredRequests",
]

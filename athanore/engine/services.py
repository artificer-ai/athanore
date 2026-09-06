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

Two members are deliberately not implementations yet, and both fail loudly
rather than plausibly:

- :attr:`TaskServices.requests` is a :class:`RequestsPort`. The port is
  the contract T033's ``human_input`` is written against; the
  implementation is T032's, and until it is wired every method raises.
- :meth:`LeaseService.released` is T026's. Releasing a slot means moving
  the task to ``waiting``, handing the lease back and re-acquiring it
  from the pool's re-admit queue (04 §Waiting); a version of it that
  merely did nothing would look like it worked, under ``workers=1``,
  right up to the first deadlock.

:attr:`TaskServices.events` is the one member with a rule of its own. A
plugin or a body may publish, but only into the ``plugin.`` namespace:
the rest of the vocabulary describes state the engine owns, and a body
that could publish ``task.done`` could tell every SSE client and every
plugin subscriber that a task it is still running has finished.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol, cast

from athanore.events.model import Event
from athanore.events.names import PLUGIN_PREFIX, EventName, is_known
from athanore.events.payloads import (
    LogAppended,
    SubmissionAccepted,
    SubmissionRejected,
    ValidationError,
)
from athanore.store.clock import now
from athanore.store.rows import (
    AnswerRow,
    LogAuthor,
    LogEntryRow,
    LogKind,
    RequestKind,
    RequestMode,
    RequestRow,
    RunRow,
    SubmissionRow,
)
from athanore.store.uow import Store

#: How much of an entry ``log.appended`` carries (18 §Log and stats). The
#: rest is fetched by id: an event never carries full log text.
PREVIEW_CHARS = 200


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
    answer arrives. That pair is :meth:`released`, and it is T026's.
    """

    def __init__(self, *, task_id: int) -> None:
        self._task_id = task_id

    def released(
        self, request_id: int | None = None
    ) -> AbstractAsyncContextManager[None]:
        """Give the slot back for the duration of the block.

        Not implemented until T026. It raises rather than yielding: a
        no-op would hold the slot through the wait, which under the
        default ``workers=1`` is one question stalling the whole server —
        the exact MVP failure 04 §Waiting exists to fix, and one that
        would look like nothing at all until a second run was queued.
        """
        raise NotImplementedError(
            "TaskServices.lease.released() is implemented in T026 (04 §Waiting)"
        )


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


class RequestsPort(Protocol):
    """What ``human_input`` and the agent bridge need of the request layer.

    Named here as a protocol because ``athanore.requests`` is an
    independent sibling of ``athanore.engine`` in the middle tier (02
    §Layering): the engine states the shape it hands a body, and T032
    supplies the object that satisfies it, wired by the runner.

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
    """A :class:`RequestsPort` that is not there yet (T032).

    Every method raises. The alternative — a port that returned ``None``
    or an empty answer — would let ``human_input`` look like it asked and
    silently take a default, which is the one failure mode a human-in-the-
    loop feature cannot have.
    """

    _MESSAGE = "TaskServices.requests is wired in T032 (06 §Service)"

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

    async def wait(
        self,
        request_id: int,
        timeout: float | None = None,  # noqa: ASYNC109 - the port's signature
    ) -> AnswerRow:
        raise NotImplementedError(self._MESSAGE)

    async def poll(self, request_id: int, wait_s: float) -> AnswerRow | None:
        raise NotImplementedError(self._MESSAGE)


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
        requests: RequestsPort | None = None,
    ) -> None:
        self.log = LogService(store, run_id=run_id, task_id=task_id, node=node)
        self.submissions = SubmissionService(
            store, run_id=run_id, task_id=task_id, node=node
        )
        self.requests: RequestsPort = (
            UnwiredRequests() if requests is None else requests
        )
        self.run = RunService(store, run_id=run_id)
        self.lease = LeaseService(task_id=task_id)
        self.events = EventPort(
            store, run_id=run_id, task_id=task_id, workflow=workflow
        )
        #: The transcript flusher. T023a.
        self.stream = None


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
    "RequestsPort",
    "RunService",
    "SubmissionService",
    "TaskServices",
    "UnwiredRequests",
]

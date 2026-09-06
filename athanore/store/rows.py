"""Domain enums and the read models the repositories return.

The statuses and their meanings are 03 §State machines; the fields mirror
the columns of 07 §Schema, one model per table. There is no ORM in this
build, so a repository turns a Core ``Row`` into one of these and hands it
out: every model is ``frozen=True``, which makes a row a value that cannot
drift after the connection it came from is closed.

Two of them are not tables. :class:`RunSummary` is a run plus the
aggregates 08 §Runs lists on the list endpoint, computed by one grouped
query rather than a per-run loop (07 §Repositories); :class:`RunStats` is
the total of the per-attempt ``tasks.stats`` entries.

The module imports nothing from ``athanore``: ``store`` is a bottom-tier
module whose siblings — ``events`` in particular — are independent of it
(02 §Layering), which is also why :class:`EventRow` restates the event
envelope rather than reusing ``athanore.events.model.Event``.

JSON columns whose shape belongs to another document stay ``Any`` or a
plain object here (``payload``, ``result``, ``output``, ``lineage``,
``stats``, a request's ``options``/``schema``/``tool_call``): this module
is the store's vocabulary, not a second copy of 05's stats entry or 18's
payloads. The one exception is :class:`BranchFrame`, whose four fields 04
§Branch frames fixes and which the engine and the graph view walk field by
field.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# --------------------------------------------------------------------------
# Enums
# --------------------------------------------------------------------------


class RunStatus(StrEnum):
    """The run state machine of 03.

    ``queued`` is new in v1: a run that exists but has dispatched nothing,
    so "waiting for a slot" is visible. The three terminal states are
    re-openable by retry, rerun and move.
    """

    queued = "queued"
    running = "running"
    paused = "paused"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class TaskStatus(StrEnum):
    """The task state machine of 03.

    ``waiting`` is a body parked in ``human_input``; it holds no pool slot
    (04 §Waiting). ``failed`` is the record of one attempt — the retry is a
    new row — and ``dead_letter`` is the attempt that exhausted them.
    """

    ready = "ready"
    in_progress = "in_progress"
    waiting = "waiting"
    done = "done"
    failed = "failed"
    dead_letter = "dead_letter"
    cancelled = "cancelled"


class LogAuthor(StrEnum):
    """Who wrote a work-log entry."""

    agent = "agent"
    engine = "engine"
    user = "user"


class LogKind(StrEnum):
    """What a work-log entry is, for filtering (the agent view drops
    ``stats``; 08 §Agent-facing)."""

    deliverable = "deliverable"
    note = "note"
    stats = "stats"
    failure = "failure"


class ChunkKind(StrEnum):
    """The kinds of the agent transcript (05 §The ACP client).

    ``text`` and ``thought`` are the assistant's message and reasoning
    chunks, ``tool_call``/``tool_result`` the ACP tool updates, ``notice``
    a line the façade itself wrote.
    """

    text = "text"
    thought = "thought"
    tool_call = "tool_call"
    tool_result = "tool_result"
    notice = "notice"


class RequestMode(StrEnum):
    """The shape of the answer a request expects (06 §The model)."""

    options = "options"
    form = "form"
    text = "text"


class RequestSource(StrEnum):
    """Who raised the request: the agent mid-turn, or the node body."""

    agent = "agent"
    node = "node"


class RequestKind(StrEnum):
    """What the request is about. A label for the UI; nothing keys on it."""

    permission = "permission"
    elicitation = "elicitation"
    question = "question"


class AnswerAuthor(StrEnum):
    """Who answered. ``engine`` is a headless fallback: a permission
    timeout action or a declined elicitation (06 §Timeouts)."""

    user = "user"
    engine = "engine"


# --------------------------------------------------------------------------
# Read models
# --------------------------------------------------------------------------


class ReadModel(BaseModel):
    """Base for every read model: a frozen value object.

    Named for what it is rather than ``Row``, which is SQLAlchemy's name
    for what a repository converts *from*.
    """

    model_config = ConfigDict(frozen=True)


class RunRow(ReadModel):
    """One row of ``runs`` (07 §Schema).

    ``position`` is the list order — 03 renamed it from ``priority`` so it
    stops colliding with node priority. ``output`` is the terminal node's
    return value, and ``None`` both before the run ends and when the run
    ended by returning ``None``; ``finished`` is the field that says which.
    """

    id: str
    workflow: str
    title: str
    description: str = ""
    status: RunStatus
    output: Any = None
    position: int
    created: datetime
    updated: datetime
    finished: datetime | None = None


class RunSummary(RunRow):
    """A run plus the aggregates the list endpoint shows (08 §Runs).

    ``current_nodes`` are the nodes with an in-progress or waiting task —
    plural because a fan-out puts a run in several at once — and
    ``pending_requests`` counts its unanswered, non-stale requests. Both
    come from the grouped query in ``RunRepo.list`` (07 §Repositories).
    ``unregistered`` is not stored: it says the run's workflow is not
    registered on this server, so the run is shown but parked (03 §Run).
    """

    current_nodes: list[str] = []
    pending_requests: int = 0
    unregistered: bool = False


class RunStats(ReadModel):
    """The agent totals of a run, summed over the per-attempt entries.

    Every field is optional and nothing is zero-filled: a provider that
    reports no cost leaves ``cost`` absent rather than claiming zero (01
    §Real data only). ``duration_s`` is the sum of the attempts' durations,
    not wall-clock time, which fan-out would make meaningless.
    """

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cost: float | None = None
    tool_calls: int | None = None
    duration_s: float | None = None


class BranchFrame(ReadModel):
    """One frame of a task's fan-out stack (04 §Branch frames).

    A fan-out of ``count`` branches from task ``fanout`` pushes one of
    these onto each child, with ``key`` the payload that branch was given —
    the branch's identity. Frames nest: a branch that fans out again pushes
    a second frame, outermost first.
    """

    fanout: int
    index: int
    count: int
    key: Any = None


class TaskRow(ReadModel):
    """One row of ``tasks``: one attempt of one node in one run.

    **No token.** ``token_hash`` is the SHA-256 the claim wrote (07), and it
    carries ``exclude=True`` so it is absent from ``model_dump()``: an
    operator response cannot leak what the model will not serialize (12
    §Task tokens, invariant 5 of 03). It is ``None`` while the task is
    ``ready``.

    ``terminal`` marks a task that finished ``done`` with no transitions,
    so its ``result`` is a branch output (04 §Routing edge cases).
    """

    id: int
    run_id: str
    node: str
    attempt: int
    status: TaskStatus
    payload: Any = None
    result: Any = None
    error: str | None = None
    priority: int
    explicit: bool = False
    token_hash: str | None = Field(default=None, exclude=True)
    stats: dict[str, Any] | None = None
    lineage: dict[str, Any] | None = None
    terminal: bool = False
    branch: list[BranchFrame] = []
    created: datetime
    started: datetime | None = None
    finished: datetime | None = None


class LogEntryRow(ReadModel):
    """One row of ``log_entries``: the work log, append-only (03).

    ``kind`` is absent on a plain entry; the ``[stats]`` line keeps its text
    form here and carries the structured dict in the ``agent.stats`` event.
    """

    id: int
    run_id: str
    task_id: int | None = None
    node: str
    author: LogAuthor
    kind: LogKind | None = None
    text: str
    created: datetime


class SubmissionRow(ReadModel):
    """One row of ``submissions``: a value an agent submitted.

    Only payloads that passed the declared model are stored, and the latest
    wins for the body (03). A submission never routes anything.
    """

    id: int
    task_id: int
    payload: Any = None
    created: datetime


class StreamChunkRow(ReadModel):
    """One row of ``stream_chunks``: a segment of the agent transcript.

    ``seq`` is unique per task and is the cursor
    ``GET /api/tasks/{id}/stream?after=`` pages by.
    """

    id: int
    task_id: int
    seq: int
    kind: ChunkKind
    text: str
    created: datetime


class RequestRow(ReadModel):
    """One row of ``requests``: something that blocks on a person (06).

    ``ordinal`` numbers the node-raised requests of one task row so a body
    that re-executes after a restart re-attaches to the request it already
    asked instead of asking again (06 §Restart durability); it is ``None``
    for agent-raised requests.

    The JSON-schema column is ``schema_`` in Python — a field named
    ``schema`` shadows an attribute of ``BaseModel`` — and keeps ``schema``
    as its alias, which is the name 08 fixes on the wire.
    """

    # ``populate_by_name`` so a repository can pass ``schema_=`` as well as
    # the wire name the alias fixes. The alias is split in two rather than
    # written as ``alias=``, which would also rename the constructor
    # parameter for a type checker.
    model_config = ConfigDict(frozen=True, populate_by_name=True)

    id: int
    run_id: str
    task_id: int
    ordinal: int | None = None
    prompt: str
    mode: RequestMode
    source: RequestSource
    kind: RequestKind
    options: list[dict[str, Any]] | None = None
    schema_: dict[str, Any] | None = Field(
        default=None, validation_alias="schema", serialization_alias="schema"
    )
    tool_call: dict[str, Any] | None = None
    created: datetime


class AnswerRow(ReadModel):
    """One row of ``answers``: the one answer a request may have.

    Keyed by ``request_id`` — there is no separate id, because an answer
    without its request does not exist. ``option_id`` is set for an
    ``options`` request and ``value`` for ``text`` and ``form``.
    ``consumed`` records that the waiter took it (06).
    """

    request_id: int
    author: AnswerAuthor
    option_id: str | None = None
    value: Any = None
    consumed: bool = False
    created: datetime


class EventRow(ReadModel):
    """One row of ``events``: the audit trail and the SSE feed (03).

    ``id`` is the monotonic SSE cursor, so a stored event always has one —
    unlike the in-flight envelope on the bus, where it is assigned by the
    insert. ``run_id`` is absent on ``engine.*`` events and ``task_id`` on
    everything that is not task-scoped. ``task.stream`` is never stored, so
    it never appears as a row.
    """

    id: int
    run_id: str | None = None
    task_id: int | None = None
    name: str
    data: dict[str, Any] = {}
    created: datetime

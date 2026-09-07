"""Typed payloads for the event vocabulary (18, normative).

One model per :class:`~athanore.events.names.EventName`, field for field as
18 §Payloads fixes them, plus the per-name envelopes and the discriminated
:data:`EventEnvelope` union the SSE feed and the generated TypeScript client
are built from (18 §Typing, D53).

Two rules from 18 are enforced here rather than left to each caller:

- a field marked ``?`` is **absent**, never ``null`` (01 §Real data only), so
  the base serializer drops optional fields that are ``None`` and keeps
  required ones (``run.completed``'s ``output`` is legitimately ``null``);
- unknown fields are refused, so a payload that drifts from 18 fails at the
  publisher rather than reaching a consumer.

Fields that 18 types with a domain enum (``RunStatus``, ``TaskStatus``,
``RequestMode``, ``RequestKind``, ``RequestSource``, ``LogAuthor``,
``LogKind``) are ``str`` here: those enums live in ``athanore.store.rows``,
and ``events`` is an independent sibling of ``store`` in the bottom tier, so
it may not import them (02 §Layering, D81).
"""

from __future__ import annotations

from datetime import datetime
from functools import cache
from types import NoneType, UnionType
from typing import Annotated, Any, Literal, Union, cast, get_args, get_origin

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    GetJsonSchemaHandler,
    SerializerFunctionWrapHandler,
    Tag,
    field_validator,
    model_serializer,
)
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import CoreSchema

from athanore.events.names import PLUGIN_PREFIX, EventName, is_known

# --------------------------------------------------------------------------
# Base
# --------------------------------------------------------------------------


def _admits_none(annotation: Any) -> bool:
    """Whether a field annotated ``annotation`` can hold ``None``."""
    if annotation is None or annotation is NoneType or annotation is Any:
        return True
    if get_origin(annotation) in (Union, UnionType):
        return any(_admits_none(arg) for arg in get_args(annotation))
    return False


@cache
def _wire(model: type[BaseModel]) -> tuple[dict[str, str], frozenset[str]]:
    """Serialization keys for ``model``: renames, and which may be omitted.

    A field's wire key is its serialization alias where it has one
    (``task.cancelled`` carries ``from``, which is not a Python
    identifier).

    A key is omittable — one of 18's ``?`` fields — only if the field has a
    default *and* its annotation admits ``None``, because that pair is what
    it takes for ``_omit_absent`` to ever drop it. A ``Literal`` with a
    default, which is how every envelope pins its own ``name``, is
    therefore not omittable: the wire always carries it.
    """
    renames: dict[str, str] = {}
    omittable: set[str] = set()
    for name, field in model.model_fields.items():
        key = field.serialization_alias or name
        if key != name:
            renames[name] = key
        if not field.is_required() and _admits_none(field.annotation):
            omittable.add(key)
    return renames, frozenset(omittable)


class EventModel(BaseModel):
    """Base for every payload and envelope: 18's absent-not-null rule."""

    model_config = ConfigDict(extra="forbid")

    @model_serializer(mode="wrap")
    def _omit_absent(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        renames, omittable = _wire(type(self))
        dumped: dict[str, Any] = handler(self)
        out: dict[str, Any] = {}
        for name, value in dumped.items():
            key = renames.get(name, name)
            if value is None and key in omittable:
                continue
            out[key] = value
        return out

    @classmethod
    def __get_pydantic_json_schema__(
        cls, core_schema: CoreSchema, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        """Describe the wire shape, not the serializer's return type.

        ``_omit_absent`` is annotated ``-> dict[str, Any]``, and pydantic
        takes a model serializer's return type as the model's
        *serialization* schema — which is the mode OpenAPI generates a
        response in. Left alone, every event in the document would be
        ``{"type": "object", "additionalProperties": true}``: 18 §Typing
        promises a ``oneOf`` per event and a discriminated union in the
        generated TypeScript, and an opaque object delivers neither.

        Dropping the ``serialization`` entry before handing the core
        schema on makes serialization render what validation renders —
        this model's own fields.

        Validation's ``required`` is then the wrong list: it omits every
        field that has a default, and a default is only half of what makes
        a field absent on the wire. ``_omit_absent`` drops a key when its
        value is ``None`` *and* the key is omittable, so the omittable set
        of :func:`_wire` — a default and an annotation that admits ``None``
        — is exactly what a client may not find. Everything else is
        required, including the ``Literal`` ``name`` each envelope pins
        itself with, which 18 §Typing tags the union by and 18 §Envelope
        never lists among the fields that may be absent (T048).
        """

        described = {
            key: value for key, value in core_schema.items() if key != "serialization"
        }
        schema = handler(cast(CoreSchema, described))
        described_schema = handler.resolve_ref_schema(schema)
        properties = described_schema.get("properties", {})
        renames, omittable = _wire(cls)
        # A renamed field is keyed here by whichever spelling the schema
        # uses, so neither of a renamed omittable field's two may end up
        # required.
        absent = omittable.union(
            name for name, key in renames.items() if key in omittable
        )
        required = [key for key in properties if key not in absent]
        if required:
            described_schema["required"] = required
        else:
            described_schema.pop("required", None)
        return schema


# --------------------------------------------------------------------------
# Payloads — runs
# --------------------------------------------------------------------------


class RunChanges(EventModel):
    """The fields an edit or an op changed on a run; only those it changed."""

    title: str | None = None
    description: str | None = None
    status: str | None = None


class RunCreated(EventModel):
    workflow: str
    title: str
    position: int


class RunStarted(EventModel):
    """The first claim of the run."""

    task_id: int
    node: str


class RunUpdated(EventModel):
    changed: RunChanges


class RunReordered(EventModel):
    position: int
    previous: int


class RunPaused(EventModel):
    pass


class RunResumed(EventModel):
    pass


class RunCancelled(EventModel):
    cancelled_tasks: list[int]


class RunDeleted(EventModel):
    """The last event of a run: it is deleted with the run, so SSE only."""

    workflow: str
    title: str


class RunCompleted(EventModel):
    """``output`` follows the shape rule of 04 §Routing edge cases.

    ``node`` and ``task_id`` are the last landing task. ``output`` is
    required and may be ``null``: a body that returns ``None`` terminates
    the run with that value, which is not the same as an unknown one.
    """

    node: str
    task_id: int
    output: Any
    terminal_tasks: list[int]


class RunFailed(EventModel):
    """``code`` is set when the run stalled on a partial join."""

    node: str
    task_id: int
    error: str
    code: Literal["join_incomplete"] | None = None


# --------------------------------------------------------------------------
# Payloads — tasks
# --------------------------------------------------------------------------

EnqueueReason = Literal[
    "start",
    "transition",
    "retry",
    "rerun",
    "move",
    "manual_retry",
    "set_status",
    "join",
]


class BranchFrame(EventModel):
    """One fan-out frame of a task's branch, without its (large) key."""

    fanout: int
    index: int
    count: int


class TaskEnqueued(EventModel):
    """``branch`` omits ``key``; for ``reason=join`` ``from_task`` is the
    fan-out task and ``arrivals`` lists the arriving tasks."""

    node: str
    attempt: int
    reason: EnqueueReason
    from_task: int | None = None
    payload_present: bool
    branch: list[BranchFrame]
    arrivals: list[int] | None = None


class JoinArrived(EventModel):
    """One per branch reaching a join.

    ``arrived == count`` means the join task was enqueued in the same
    transaction.
    """

    join: str
    fanout_task: int
    index: int
    count: int
    arrived: int
    late: bool


class TaskStarted(EventModel):
    node: str
    attempt: int


class TaskDone(EventModel):
    node: str
    attempt: int
    transitions: list[str]
    terminal: bool


class TaskFailed(EventModel):
    node: str
    attempt: int
    error: str
    retryable: bool
    will_retry: bool
    retry_task_id: int | None = None


class TaskDeadLettered(EventModel):
    node: str
    attempt: int
    error: str


class TaskWaiting(EventModel):
    node: str
    request_id: int


class TaskResumed(EventModel):
    node: str
    request_id: int
    waited_s: float


class TaskCancelled(EventModel):
    node: str
    from_: str = Field(
        validation_alias=AliasChoices("from", "from_"), serialization_alias="from"
    )
    reason: Literal["cancel", "move", "delete", "set_status"]


class TaskMoved(EventModel):
    node: str
    to: str
    new_task_id: int


class TaskStatusSet(EventModel):
    node: str
    from_: str = Field(
        validation_alias=AliasChoices("from", "from_"), serialization_alias="from"
    )
    to: str


class TaskStream(EventModel):
    """Ephemeral; the content is fetched from ``/api/tasks/{id}/stream``."""

    seq_from: int
    seq_to: int


# --------------------------------------------------------------------------
# Payloads — submissions and requests
# --------------------------------------------------------------------------


class SubmissionAccepted(EventModel):
    """The payload itself is not in the event; fetch the task."""

    node: str
    submission_id: int


class ValidationError(EventModel):
    """One pydantic error, as ``ValidationError.errors()`` reports it."""

    loc: list[str | int]
    msg: str
    type: str


class SubmissionRejected(EventModel):
    node: str
    errors: list[ValidationError]


class SubmissionRepair(EventModel):
    node: str
    turn: int
    reason: Literal["nothing_submitted", "rejected"]


class RequestOpened(EventModel):
    request_id: int
    mode: str
    kind: str
    source: str
    node: str
    ordinal: int | None = None


class RequestAnswered(EventModel):
    """``value`` is not in the event (may be large or sensitive); fetch it."""

    request_id: int
    author: Literal["user", "engine"]
    option_id: str | None = None


# --------------------------------------------------------------------------
# Payloads — log and stats
# --------------------------------------------------------------------------


class LogAppended(EventModel):
    """``preview`` is the first 200 characters of the entry."""

    log_id: int
    author: str
    node: str
    kind: str | None = None
    preview: str


class AgentStats(EventModel):
    """The stats entry of 05 §Stats entry verbatim.

    Every measurement is optional because 05 omits what it cannot
    determine rather than zero-filling it (01 §Real data only).
    """

    node: str
    attempt: int
    status: Literal["ok", "failed"]
    reason: (
        Literal[
            "refusal",
            "cancelled",
            "truncated",
            "timeout",
            "shutdown",
            "transport",
            "no_submission",
        ]
        | None
    ) = None
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    tool_calls: int | None = None
    cost: float | None = None
    duration_s: float
    session_id: str | None = None
    repair_turns: int | None = None
    denied_permissions: int | None = None


# --------------------------------------------------------------------------
# Payloads — engine
# --------------------------------------------------------------------------


class EngineRecovered(EventModel):
    """Rows reset to ``ready`` at startup. No ``run_id``."""

    task_ids: list[int]


class EngineStopping(EventModel):
    """Attempts interrupted by a shutdown (04 §Shutdown). No ``run_id``."""

    task_ids: list[int]


# --------------------------------------------------------------------------
# Envelopes
# --------------------------------------------------------------------------


class EventFrame(EventModel):
    """The fields every event carries; ``name`` and ``data`` are per variant.

    ``id`` is the SSE cursor and is absent on ephemeral events; ``run_id`` is
    absent on ``engine.*``; ``task_id`` is present on the task-scoped events
    and on ``log.appended`` when the entry has a task.
    """

    id: int | None = None
    run_id: str | None = None
    task_id: int | None = None
    created: datetime


class RunCreatedEvent(EventFrame):
    name: Literal[EventName.run_created] = EventName.run_created
    data: RunCreated


class RunStartedEvent(EventFrame):
    name: Literal[EventName.run_started] = EventName.run_started
    data: RunStarted


class RunUpdatedEvent(EventFrame):
    name: Literal[EventName.run_updated] = EventName.run_updated
    data: RunUpdated


class RunReorderedEvent(EventFrame):
    name: Literal[EventName.run_reordered] = EventName.run_reordered
    data: RunReordered


class RunPausedEvent(EventFrame):
    name: Literal[EventName.run_paused] = EventName.run_paused
    data: RunPaused


class RunResumedEvent(EventFrame):
    name: Literal[EventName.run_resumed] = EventName.run_resumed
    data: RunResumed


class RunCancelledEvent(EventFrame):
    name: Literal[EventName.run_cancelled] = EventName.run_cancelled
    data: RunCancelled


class RunDeletedEvent(EventFrame):
    name: Literal[EventName.run_deleted] = EventName.run_deleted
    data: RunDeleted


class RunCompletedEvent(EventFrame):
    name: Literal[EventName.run_completed] = EventName.run_completed
    data: RunCompleted


class RunFailedEvent(EventFrame):
    name: Literal[EventName.run_failed] = EventName.run_failed
    data: RunFailed


class TaskEnqueuedEvent(EventFrame):
    name: Literal[EventName.task_enqueued] = EventName.task_enqueued
    data: TaskEnqueued


class JoinArrivedEvent(EventFrame):
    name: Literal[EventName.join_arrived] = EventName.join_arrived
    data: JoinArrived


class TaskStartedEvent(EventFrame):
    name: Literal[EventName.task_started] = EventName.task_started
    data: TaskStarted


class TaskDoneEvent(EventFrame):
    name: Literal[EventName.task_done] = EventName.task_done
    data: TaskDone


class TaskFailedEvent(EventFrame):
    name: Literal[EventName.task_failed] = EventName.task_failed
    data: TaskFailed


class TaskDeadLetteredEvent(EventFrame):
    name: Literal[EventName.task_dead_lettered] = EventName.task_dead_lettered
    data: TaskDeadLettered


class TaskWaitingEvent(EventFrame):
    name: Literal[EventName.task_waiting] = EventName.task_waiting
    data: TaskWaiting


class TaskResumedEvent(EventFrame):
    name: Literal[EventName.task_resumed] = EventName.task_resumed
    data: TaskResumed


class TaskCancelledEvent(EventFrame):
    name: Literal[EventName.task_cancelled] = EventName.task_cancelled
    data: TaskCancelled


class TaskMovedEvent(EventFrame):
    name: Literal[EventName.task_moved] = EventName.task_moved
    data: TaskMoved


class TaskStatusSetEvent(EventFrame):
    name: Literal[EventName.task_status_set] = EventName.task_status_set
    data: TaskStatusSet


class TaskStreamEvent(EventFrame):
    """Ephemeral: published to the bus and SSE, never stored, no ``id``."""

    name: Literal[EventName.task_stream] = EventName.task_stream
    data: TaskStream


class SubmissionAcceptedEvent(EventFrame):
    name: Literal[EventName.submission_accepted] = EventName.submission_accepted
    data: SubmissionAccepted


class SubmissionRejectedEvent(EventFrame):
    name: Literal[EventName.submission_rejected] = EventName.submission_rejected
    data: SubmissionRejected


class SubmissionRepairEvent(EventFrame):
    name: Literal[EventName.submission_repair] = EventName.submission_repair
    data: SubmissionRepair


class RequestOpenedEvent(EventFrame):
    name: Literal[EventName.request_opened] = EventName.request_opened
    data: RequestOpened


class RequestAnsweredEvent(EventFrame):
    name: Literal[EventName.request_answered] = EventName.request_answered
    data: RequestAnswered


class LogAppendedEvent(EventFrame):
    name: Literal[EventName.log_appended] = EventName.log_appended
    data: LogAppended


class AgentStatsEvent(EventFrame):
    name: Literal[EventName.agent_stats] = EventName.agent_stats
    data: AgentStats


class EngineRecoveredEvent(EventFrame):
    name: Literal[EventName.engine_recovered] = EventName.engine_recovered
    data: EngineRecovered


class EngineStoppingEvent(EventFrame):
    name: Literal[EventName.engine_stopping] = EventName.engine_stopping
    data: EngineStopping


class PluginEvent(EventFrame):
    """``plugin.<workflow>.<name>``: the vocabulary's open end.

    The handler's data is free-form, so the wire carries whatever it passed
    to ``ctx.services.events.publish``; 18 requires a JSON object, and the
    registry — not this model — enforces that ``<workflow>`` is the
    publishing workflow.

    ``name`` is the only one in the union that is not a
    :class:`~typing.Literal`, and it is declared as the whole vocabulary
    — ``EventName | str`` — rather than as a bare ``str``. The two are
    the same set of strings, so nothing is widened; what the wider
    spelling buys is a *reference* to the enum in the generated document,
    which is where 08 §OpenAPI wants the event-name enum published and
    where the SPA's TypeScript union is generated from (13 §Contract
    tests). The validator below is what actually narrows this field, to
    the ``plugin.`` namespace.
    """

    name: EventName | str
    data: dict[str, Any]

    @field_validator("name")
    @classmethod
    def _plugin_name(cls, value: str) -> str:
        if not value.startswith(PLUGIN_PREFIX) or not is_known(value):
            raise ValueError(
                "a plugin event is named plugin.<workflow>.<name>, "
                f"with identifier segments; got {value!r}"
            )
        return value


def _envelope_tag(value: Any) -> str:
    """Route an envelope by its ``name``, with ``plugin.*`` as the open end."""
    if isinstance(value, dict):
        name = value.get("name")
    else:
        name = getattr(value, "name", None)
    if not isinstance(name, str):
        return ""
    return PLUGIN_PREFIX if name.startswith(PLUGIN_PREFIX) else name


#: Every event on the wire, discriminated on ``name`` (18 §Typing). The
#: variants fix ``data``'s shape per name; ``plugin.*`` falls through to
#: :class:`PluginEvent`.
EventEnvelope = Annotated[
    Union[  # noqa: UP007 — Annotated[X | Y, Tag(...)] members need the alias form
        Annotated[RunCreatedEvent, Tag(EventName.run_created.value)],
        Annotated[RunStartedEvent, Tag(EventName.run_started.value)],
        Annotated[RunUpdatedEvent, Tag(EventName.run_updated.value)],
        Annotated[RunReorderedEvent, Tag(EventName.run_reordered.value)],
        Annotated[RunPausedEvent, Tag(EventName.run_paused.value)],
        Annotated[RunResumedEvent, Tag(EventName.run_resumed.value)],
        Annotated[RunCancelledEvent, Tag(EventName.run_cancelled.value)],
        Annotated[RunDeletedEvent, Tag(EventName.run_deleted.value)],
        Annotated[RunCompletedEvent, Tag(EventName.run_completed.value)],
        Annotated[RunFailedEvent, Tag(EventName.run_failed.value)],
        Annotated[TaskEnqueuedEvent, Tag(EventName.task_enqueued.value)],
        Annotated[JoinArrivedEvent, Tag(EventName.join_arrived.value)],
        Annotated[TaskStartedEvent, Tag(EventName.task_started.value)],
        Annotated[TaskDoneEvent, Tag(EventName.task_done.value)],
        Annotated[TaskFailedEvent, Tag(EventName.task_failed.value)],
        Annotated[TaskDeadLetteredEvent, Tag(EventName.task_dead_lettered.value)],
        Annotated[TaskWaitingEvent, Tag(EventName.task_waiting.value)],
        Annotated[TaskResumedEvent, Tag(EventName.task_resumed.value)],
        Annotated[TaskCancelledEvent, Tag(EventName.task_cancelled.value)],
        Annotated[TaskMovedEvent, Tag(EventName.task_moved.value)],
        Annotated[TaskStatusSetEvent, Tag(EventName.task_status_set.value)],
        Annotated[TaskStreamEvent, Tag(EventName.task_stream.value)],
        Annotated[SubmissionAcceptedEvent, Tag(EventName.submission_accepted.value)],
        Annotated[SubmissionRejectedEvent, Tag(EventName.submission_rejected.value)],
        Annotated[SubmissionRepairEvent, Tag(EventName.submission_repair.value)],
        Annotated[RequestOpenedEvent, Tag(EventName.request_opened.value)],
        Annotated[RequestAnsweredEvent, Tag(EventName.request_answered.value)],
        Annotated[LogAppendedEvent, Tag(EventName.log_appended.value)],
        Annotated[AgentStatsEvent, Tag(EventName.agent_stats.value)],
        Annotated[EngineRecoveredEvent, Tag(EventName.engine_recovered.value)],
        Annotated[EngineStoppingEvent, Tag(EventName.engine_stopping.value)],
        Annotated[PluginEvent, Tag(PLUGIN_PREFIX)],
    ],
    Discriminator(_envelope_tag),
]


def _index() -> dict[EventName, type[EventFrame]]:
    """The union, keyed by name.

    Derived from :data:`EventEnvelope` rather than written out a second
    time, so a name that gains an enum member but no variant has no entry
    here — which is what the contract test reads.
    """
    index: dict[EventName, type[EventFrame]] = {}
    for member in get_args(get_args(EventEnvelope)[0]):
        variant: type[EventFrame] = get_args(member)[0]
        if variant is PluginEvent:
            continue
        annotation = variant.model_fields["name"].annotation
        for value in get_args(annotation):
            index[EventName(value)] = variant
    return index


#: Envelope class per event name; ``plugin.*`` is :class:`PluginEvent`.
ENVELOPES: dict[EventName, type[EventFrame]] = _index()

#: Payload model per event name — the ``data`` of the matching envelope.
PAYLOADS: dict[EventName, type[EventModel]] = {
    name: cast(type[EventModel], envelope.model_fields["data"].annotation)
    for name, envelope in ENVELOPES.items()
}

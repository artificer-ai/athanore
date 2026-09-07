"""``/api/agent/``: the whole of what a task token may do (08, D39).

Five routes, one credential, one task. Everything an agent is allowed to
call lives under this prefix on its own router with
:func:`~athanore.api.deps.task_auth` and its own response models, rather
than sharing the operator's routes and choosing a shape by credential the
way the MVP did: that could not be expressed in OpenAPI without ``oneOf``
tricks and made the auth dependency decide two things at once (D39). The
token is the task's — it is minted per attempt at claim, it is valid only
while that attempt is ``in_progress`` or ``waiting``, and it names the
task, so no route here takes a task id that the token did not already fix
(12 §Task tokens).

Four of the five need the attempt to be **running in this process**, and
that is the one precondition this router states itself. A submission is
recorded through the attempt's own
:class:`~athanore.engine.services.SubmissionService`, validated against
the ``output_model`` the agent façade declared on the live
:class:`~athanore.engine.context.TaskContext`; an ask is opened through
the attempt's request port with ``source="agent"``; and both of those
objects exist only between the moment the runner binds the attempt and
the moment it ends (04 §Recovery). A task with no live context is by
definition not being run here, so 08's "409 if the task is not in
progress" is exactly "no live context" — there is no second status check
to disagree with it.

What the agent is *shown* is narrower than what an operator sees. The
work log comes back without its ``stats`` entries (D56): token counts and
costs are operator information, and an agent reading its own back learns
nothing it can act on. Nothing here reports a token, an id of another
task, or the internals of a request it did not open.

The two decisions worth naming:

**Validation happens once, in the function the agent façade also uses.**
:func:`~athanore.agents.submissions.validate_submission` is the predicate
here and in the repair loop, so the errors a model is shown in a 422 and
the errors quoted back to it in 19's repair turn are the same list, and
``ctx.last_rejection`` is what carries them between the two (T035).

**A rejected submission is not stored.** ``submissions.reject`` emits
``submission.rejected`` and writes no row, so
``SubmissionService.latest`` never returns a payload a body must not act
on — "the latest *valid* submission wins" (05 §Submissions).
"""

from __future__ import annotations

from typing import Annotated, Any, Final, cast

from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi import Path as PathParam

from athanore.agents.submissions import validate_submission
from athanore.api.deps import task_auth
from athanore.api.errors import ApiError, ErrorCode
from athanore.api.schemas import (
    AgentTask,
    AnswerPoll,
    Ask,
    AskOut,
    LogEntry,
    LogRef,
    LogText,
    Ok,
)
from athanore.engine import Engine
from athanore.engine.context import TaskContext
from athanore.engine.errors import Conflict, NotFound
from athanore.engine.services import RequestBackend
from athanore.requests.errors import RequestNotFound
from athanore.store import rows
from athanore.store.rows import TaskRow
from athanore.store.uow import Store

__all__ = ["MAX_WAIT", "router"]

router = APIRouter(prefix="/api/agent/tasks", tags=["agent"])

#: The path parameter every route takes. It is the task the token was
#: minted for — :func:`~athanore.api.deps.task_auth` refuses any other —
#: so it names the attempt rather than selecting one.
TaskId = Annotated[int, PathParam(description="The task the token was minted for.")]

#: The attempt this request's token belongs to. Depending on
#: :func:`~athanore.api.deps.task_auth` by parameter rather than on the
#: router is what gives each route the row it authenticated, instead of
#: reading it again.
Authenticated = Annotated[TaskRow, Depends(task_auth)]

#: The longest an agent may hold a long-poll open (08 §Agent-facing). A
#: larger ``?wait=`` is clamped to it rather than refused: an agent that
#: asked for ten minutes wants the answer, and the loop of 19's ask
#: instructions is what it is told to write.
MAX_WAIT: Final = 120.0

#: The work-log kinds an agent is not shown (D56).
HIDDEN_LOG_KINDS: Final = (rows.LogKind.stats,)


# --------------------------------------------------------------------------
# The collaborators, and what their absence means
# --------------------------------------------------------------------------


def _store(request: Request, task_id: int) -> Store:
    """The store this task is in, or the 404 there is no task without.

    ``create_app()`` takes its collaborators rather than building them,
    so an application with no store is a real thing (the OpenAPI dump is
    one). No caller gets this far without one — :func:`task_auth` refuses
    every token when there is no store to check it against — so this is
    the same refusal said in the language of the route rather than of the
    door: a server that holds no attempts holds no task with this id.
    """

    store: Store | None = request.app.state.store
    if store is None:
        raise NotFound(f"task {task_id} does not exist: this server has no store")
    return store


def _maybe_live(request: Request, task_id: int) -> TaskContext | None:
    """The context of the attempt running here, or ``None``.

    The cast is the registry's structural typing narrowed back: it stores
    anything carrying a ``task_id`` so that :mod:`athanore.engine.live`
    need not import the context, and the runner is the only thing that
    registers one.
    """

    engine: Engine | None = request.app.state.engine
    live = None if engine is None else engine.live.context_for(task_id)
    return None if live is None else cast("TaskContext", live)


def _live(request: Request, task_id: int) -> TaskContext:
    """The context of the attempt running here, or 409 ``conflict``.

    08's "409 if the task is not in progress", said in the one place that
    can know it: the registry of in-flight attempts (04 §Recovery). The
    row may still read ``in_progress`` after a crash — recovery has not
    turned it back into ``ready`` yet — and a submission accepted then
    would be read by nobody, because the body that would have routed on
    it is gone with the process that ran it.

    The read is :func:`_maybe_live`; what this adds is the refusal, so
    that the three routes that write have one sentence between them for
    why they would not.
    """

    ctx = _maybe_live(request, task_id)
    if ctx is None:
        raise Conflict(
            f"task {task_id} is not being run by this server: no attempt of "
            "it is live here, so nothing would read what you sent"
        )
    return ctx


def _requests(request: Request, request_id: int) -> RequestBackend:
    """The request service, or the 404 a request has without one.

    A server composed without one has a request port whose every method
    raises (04 §TaskContext), so no attempt on it ever opened a request
    and there is nothing here to poll.
    """

    engine: Engine | None = request.app.state.engine
    service = None if engine is None else engine.requests
    if service is None:
        raise RequestNotFound(
            f"no request {request_id}: this server has no request service"
        )
    return service


# --------------------------------------------------------------------------
# The read
# --------------------------------------------------------------------------


@router.get("/{task_id}", summary="Read this task: its brief and the work log")
async def get_task(request: Request, task_id: TaskId, task: Authenticated) -> AgentTask:
    """Everything the agent needs to start, and nothing else (08).

    The title and the description are the run's — the brief an operator
    submitted — and ``input`` is the payload this node was enqueued with,
    ``null`` when it had none. ``log`` is the run's work log, oldest
    first, uncapped and untruncated: it is the inter-stage channel (D4),
    it is bounded by the number of stages rather than by agent output,
    and a retried attempt reads the ``failure`` entry that says why the
    last one failed.

    The ``stats`` entries are dropped (D56). ``output_schema`` is here
    only while a façade has declared an ``output_model`` on this
    attempt's live context: the ``native`` tooling tier reads it to build
    its ``submit_result`` tool (05 §Tooling tiers), and an agent with no
    model declared is not required to submit anything.
    """

    store = _store(request, task_id)
    async with store.reader() as reader:
        run = await reader.runs.get(task.run_id)
        entries = await reader.log.list(task.run_id, exclude_kinds=HIDDEN_LOG_KINDS)
    if run is None:  # pragma: no cover - a task without its run cannot be claimed
        raise NotFound(f"run {task.run_id} of task {task_id} no longer exists")
    live = _maybe_live(request, task_id)
    model = None if live is None else live.output_model
    return AgentTask(
        task_id=task.id,
        run_id=task.run_id,
        workflow=run.workflow,
        node=task.node,
        attempt=task.attempt,
        title=run.title,
        description=run.description,
        input=task.payload,
        output_schema=None if model is None else model.model_json_schema(),
        log=[LogEntry.of(entry) for entry in entries],
    )


# --------------------------------------------------------------------------
# The writes
# --------------------------------------------------------------------------


@router.post("/{task_id}/log", summary="Append this attempt's deliverable")
async def append_log(
    request: Request, task_id: TaskId, task: Authenticated, body: LogText
) -> LogRef:
    """Write one entry to the run's work log, author ``agent``.

    The deliverable of a stage, which is what the next stage reads (D4).
    It is written through the attempt's own
    :class:`~athanore.engine.services.LogService`, so it carries this
    task's id and node and emits the ``log.appended`` the SPA re-renders
    on — the same call a node body makes, reached over HTTP.
    """

    ctx = _live(request, task_id)
    entry = await ctx.services.log.append(body.text, author=rows.LogAuthor.agent)
    return LogRef(log_id=entry.id)


@router.post("/{task_id}/submit", summary="Submit this task's structured result")
async def submit(
    request: Request,
    task_id: TaskId,
    task: Authenticated,
    payload: Annotated[
        Any,
        Body(
            description="The result, as JSON. Any shape when no `output_model` is "
            "declared; otherwise it must fit the schema `GET /api/agent/tasks/{id}` "
            "reports."
        ),
    ],
) -> Ok:
    """Record a value for this attempt, if it fits what was asked for.

    With an ``output_model`` declared, a misfit is a 422 carrying
    ``errors`` and ``schema`` and nothing is stored: the agent reads the
    two in its own tool output and can fix the shape inside the same turn
    (05 §Submissions). The rejection is also left on the context as
    ``ctx.last_rejection``, which is what 19's repair turn quotes back if
    the turn ends without a valid submission.

    With none declared, any JSON is stored as it arrived.

    Submitting twice is not an error: the **latest valid** payload wins
    (D5), and a body reads it with ``submissions.latest()``. A submission
    never routes anything — the node body decides — so an agent cannot
    move its own task.
    """

    ctx = _live(request, task_id)
    ok, errors, _normalised = validate_submission(ctx.output_model, payload)
    if ok:
        await ctx.services.submissions.accept(payload)
        return Ok()
    model = ctx.output_model
    if model is None:  # pragma: no cover - nothing fails validation without one
        raise RuntimeError("a submission was rejected with no output_model declared")
    rejection = await ctx.services.submissions.reject(errors, model.model_json_schema())
    # What 19 §Repair turn quotes: the errors and the schema the service
    # recorded, plus the payload they were about — which the event
    # deliberately does not carry (18 §Rules, D120).
    ctx.last_rejection = {**rejection, "payload": payload}
    raise ApiError(
        422, ErrorCode.validation, "submission failed validation", **rejection
    )


@router.post("/{task_id}/ask", summary="Ask the operator a question")
async def ask(
    request: Request, task_id: TaskId, task: Authenticated, body: Ask
) -> AskOut:
    """Open a request against this attempt, if the agent may ask at all.

    403 unless the façade running this attempt declared
    ``ask_policy="http"`` (05 §Policies): an agent cannot grant itself
    the right to interrupt a person, and the policy lives on the agent
    class the workflow chose. The prompt sections that tell an agent how
    to ask are omitted when it is off (19), so a 403 here is an agent
    that went looking.

    What was sent decides the mode: ``options`` for a pick-one question,
    ``schema`` for a form — whose answer is validated against that very
    schema where it lands, by the validator registered here (06
    §Service) — and neither for free text. The request is opened with
    ``source="agent"`` and no ordinal, because a re-executed attempt does
    not reproduce a turn statement for statement (06 §Restart
    durability).

    The answer does not come back here: the caller polls
    ``/requests/{rid}``, which is what lets the agent keep its turn
    rather than holding this connection open.
    """

    ctx = _live(request, task_id)
    if ctx.ask_policy != "http":
        raise ApiError(
            403,
            ErrorCode.forbidden,
            "this agent may not ask the operator: ask_policy is off",
        )
    opened = await ctx.services.requests.create_agent_request(
        body.prompt.strip(),
        mode=body.mode,
        kind=rows.RequestKind.question,
        options=body.option_dicts(),
        schema=body.schema_,
    )
    if body.schema_ is not None:
        ctx.services.requests.register_schema_validator(opened.id, body.schema_)
    return AskOut(request_id=opened.id, mode=body.mode)


# --------------------------------------------------------------------------
# The long-poll
# --------------------------------------------------------------------------


@router.get(
    "/{task_id}/requests/{request_id}", summary="Wait for the answer to a question"
)
async def poll_request(
    request: Request,
    task_id: TaskId,
    task: Authenticated,
    request_id: Annotated[int, PathParam(description="A request this task opened.")],
    wait: Annotated[
        float,
        Query(
            description="Seconds to wait for an answer before reporting that "
            f"there is none yet. Clamped to [0, {MAX_WAIT:.0f}]."
        ),
    ] = 0.0,
) -> AnswerPoll:
    """The answer, waiting up to ``wait`` seconds for one to land.

    ``wait`` is clamped to :data:`MAX_WAIT` rather than refused, so 19's
    instruction — poll with ``?wait=60`` and repeat until it says
    ``answered`` — is a loop that costs one request per minute and not a
    spin. The wait ends the moment the answer is recorded, not when the
    clamp expires.

    A request of **another** task is a 404, not someone else's answer: a
    token names one attempt and this route reads only what that attempt
    opened (12 §Task tokens).

    Nothing is claimed. An agent that lost a response and asked again
    gets the same answer again, which is what makes a dropped connection
    cost nothing (06 §Service).
    """

    service = _requests(request, request_id)
    store = _store(request, task_id)
    async with store.reader() as reader:
        view = await reader.requests.view(request_id)
    if view is None or view.task_id != task_id:
        raise RequestNotFound(f"no request {request_id} on task {task_id}")
    answer = await service.poll(request_id, max(0.0, min(wait, MAX_WAIT)))
    if answer is None:
        return AnswerPoll(request_id=request_id, answered=False)
    # The waiter is gone: this poll is the one that took the answer, and a
    # validator left registered would validate the next answer to a
    # request nobody is waiting on any more (06 §Service).
    service.unregister_validator(request_id)
    return AnswerPoll(
        request_id=request_id,
        answered=True,
        answer=answer.value if answer.option_id is None else answer.option_id,
        answered_by=answer.author,
    )

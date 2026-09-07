"""``/mcp/agent``: the agent surface, spoken as MCP (08 §MCP, D63).

The same five capabilities as ``/api/agent/``, offered as tools over the
Model Context Protocol's streamable-HTTP transport, for the ``mcp``
tooling tier of 05 §Tooling tiers: an agent whose ``initialize`` response
advertises ``mcpCapabilities.http`` is handed this URL and its token, and
never sees a curl line or the token itself in its prompt.

**It is not a second contract.** Every tool below calls the very function
:mod:`athanore.api.routers.agent` registered as a route, with the same
arguments the router would have parsed, so nothing is reachable here that
is not reachable there and neither can drift from the other. The
refusals are the same refusals — an :class:`~athanore.api.errors.ApiError`
or a domain exception — rendered as an ``isError`` tool result carrying
08 §Conventions' error body instead of as an HTTP status, because a model
reads a tool result and cannot read a status line.

Three things the protocol makes this module decide.

**There is no task id.** A tool takes only what its own call needs; the
attempt is the token's. :func:`~athanore.api.deps.live_task` is what
turns the ``X-Athanore-Token`` header into that attempt, and it is the
same predicate :func:`~athanore.api.deps.task_auth` uses for the REST
routes — so a token cannot name another task here any more than it can
there, and there is no id parameter for it to name one with.

**Auth is at the door, not in the tools.** The token is checked by
:class:`TaskTokenGuard` before a byte of MCP is parsed, and the attempt
it resolved is left on the request for the tools to read. A wrong token
is therefore an HTTP 403 with the API's error body — the transport's own
answer — rather than a JSON-RPC session that answers every call with a
refusal. A missing header is the same 403: unlike the REST routes there
is no signature for FastAPI to report a missing header against, and
"which of the two it was" is not information the door hands out (12).

**The tool list is built per request.** ``submit_result``'s input schema
*is* the live context's ``output_model`` schema (05), so it is read at
list-tools time and falls back to a free object when no model is
declared; and ``ask_operator`` is listed only when that context's
``ask_policy`` is ``"http"`` — absence is the enforcement, and an agent
that calls it anyway gets the same 403 the REST route gives. Both facts
belong to one attempt, which is why the listing cannot be static.

The transport is **stateless**: every request stands alone, carries the
token, and is authenticated on its own, which is exactly the lifetime a
task token has (12 §Task tokens). There is no session for an attempt to
outlive. DNS-rebinding protection is left off because Athanore's posture
is the one in 12 — a loopback bind by default, and a task token on every
request either way — and the body cap is the application's own
(:class:`~athanore.api.middleware.BodyLimitMiddleware`), passed in so the
two agree on one number.

The endpoint is listed in OpenAPI under the ``agent`` tag as an opaque
route: its schema is MCP's rather than REST's, so the document records
that it exists and what authenticates it and says nothing about its
bodies (08 §MCP).
"""

from __future__ import annotations

import json
from typing import Any, Final, TypeVar

from fastapi import FastAPI
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel.server import Server
from mcp.server.streamable_http_manager import (
    StreamableHTTPASGIApp,
    StreamableHTTPSessionManager,
)
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.requests import Request
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from athanore.api import VERSION
from athanore.api.deps import live_task
from athanore.api.errors import ApiError, ErrorCode, api_error_for
from athanore.api.routers import agent
from athanore.api.schemas import Ask, LogText
from athanore.engine.context import TaskContext
from athanore.settings import AthanoreSettings
from athanore.store.rows import TaskRow

__all__ = ["MCP_PATH", "PATH_ITEM", "SERVER_NAME", "TaskTokenGuard", "mount"]

#: Where the server is mounted (08 §MCP). The URL an ACP session is
#: given in the ``mcp`` tier is this path under ``public_url`` (05).
MCP_PATH: Final = "/mcp/agent"

#: The server's name on the wire. It is what an agent's tool names are
#: namespaced by in most harnesses — ``mcp__athanore__append_log`` — and
#: :mod:`athanore.agents.policies` already matches on that spelling.
SERVER_NAME: Final = "athanore"

#: The header the task token arrives in, and the only place it may (12).
TOKEN_HEADER: Final = "X-Athanore-Token"

#: Where :class:`TaskTokenGuard` leaves the attempt it authenticated, for
#: the tool handlers to read off the same request.
TASK_STATE_KEY: Final = "athanore_task"


# --------------------------------------------------------------------------
# What a tool takes
# --------------------------------------------------------------------------


class NoArgs(BaseModel):
    """``get_task``'s arguments: none.

    ``extra="forbid"`` so the schema says ``additionalProperties: false``
    and a model that invents a task id is told it invented one, rather
    than having it silently ignored.
    """

    model_config = ConfigDict(extra="forbid")


class AskArgs(Ask):
    """``ask_operator``'s arguments: :class:`Ask`, plus an optional wait.

    The REST surface splits opening a question from waiting for its
    answer, because an HTTP agent has to keep its turn while it polls. A
    tool call is already a turn the model is waiting inside, so 08 lets
    this one do both: ``wait`` seconds of long-poll, and the answer in
    the result when it lands in time.
    """

    wait: float = Field(
        default=0.0,
        ge=0.0,
        description="Seconds to wait for the answer before returning "
        f"`answered: false`. Clamped to {agent.MAX_WAIT:.0f}.",
    )


class WaitArgs(BaseModel):
    """``wait_answer``'s arguments: a request this task opened, and a wait."""

    model_config = ConfigDict(extra="forbid")

    request_id: int = Field(description="The request id `ask_operator` returned.")
    wait: float = Field(
        default=0.0,
        ge=0.0,
        description="Seconds to wait for the answer before returning "
        f"`answered: false`. Clamped to {agent.MAX_WAIT:.0f}.",
    )


#: What ``submit_result`` accepts when the node declared no
#: ``output_model``: any object, as 08 §MCP says. The REST route takes
#: any JSON at all, but a tool's arguments are an object by protocol, so
#: this is as wide as MCP can be.
FREE_OBJECT: Final[dict[str, Any]] = {
    "type": "object",
    "title": "Submission",
    "description": "The result, as JSON. This node declared no output model, "
    "so any object is accepted.",
    "additionalProperties": True,
}


# --------------------------------------------------------------------------
# 19's wording, per tool
# --------------------------------------------------------------------------
# 08 §MCP: "Tool descriptions carry the same wording as the 19 kickoff so
# the model's instructions and its tools agree." Every line below is a
# line of `docs/v1/19-agent-prompts.md` — the sentence that names the
# capability, with the curl mechanics that belong to the `http` tier left
# out, because in this tier the tool *is* the mechanics.
# `tests/api/test_mcp.py` reads the document back and checks that each
# line is still in it, so a change to 19 cannot leave these behind.

#: 19 §Kickoff, the sentence that says what reading the task is for.
GET_TASK_DESCRIPTION: Final = (
    "Start by reading your task: the title, description, and the FULL "
    "work log — deliverables and notes from every earlier stage and attempt."
)

#: 19 §Kickoff, the sentence that says what the deliverable is for.
APPEND_LOG_DESCRIPTION: Final = (
    "Your own deliverable MUST be appended to the run's work log before "
    "you finish — the next stage reads this same log."
)

#: 19 §Tier block `mcp`/`native`, the line that replaces the submission
#: instructions when an ``output_model`` is declared.
SUBMIT_RESULT_DESCRIPTION: Final = (
    "When you have finished, call submit_result; its schema is the tool's input schema."
)

#: 19 §Ask instructions: when to ask, and what the options are for.
ASK_OPERATOR_DESCRIPTION: Final = (
    "If you genuinely need something from the human operator (a "
    "decision, a missing detail), you may ask — sparingly:\n"
    'Add "options": ["a", "b"] for a pick-one question. The response '
    "carries a request_id."
)

#: 19 §Ask instructions: the loop, and what it is for.
WAIT_ANSWER_DESCRIPTION: Final = (
    'Then wait for the answer, repeating until it says "answered": true'
    "\nContinue only once you have the answer."
)


# --------------------------------------------------------------------------
# The door
# --------------------------------------------------------------------------


class TaskTokenGuard:
    """Refuse anything without a live task token, before MCP sees it.

    A pure ASGI wrapper for the same reason
    :class:`~athanore.api.middleware.BodyLimitMiddleware` is one: the app
    it guards is not a FastAPI route, so there is no dependency for
    :func:`~athanore.api.deps.task_auth` to be injected into. What it
    adds is one lookup — the token's attempt, by
    :func:`~athanore.api.deps.live_task` — and the attempt is left on the
    request's state so the tools read what the door already resolved
    rather than looking it up again per call.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        request = Request(scope)
        try:
            task = await live_task(request, request.headers.get(TOKEN_HEADER))
        except ApiError as refusal:
            await refusal.response()(scope, receive, send)
            return
        setattr(request.state, TASK_STATE_KEY, task)
        await self.app(scope, receive, send)


def _request(ctx: ServerRequestContext[Any, Any]) -> Request:
    """The HTTP request this message arrived on.

    Always present: the only transport this server is mounted behind is
    streamable HTTP, which attaches the request to every message it
    dispatches. A message without one would mean the server had been
    reached some other way, and every tool below needs the application
    the request carries.
    """

    request = ctx.request
    if not isinstance(request, Request):  # pragma: no cover - defensive
        raise RuntimeError("the MCP server was reached without an HTTP request")
    return request


def _task(request: Request) -> TaskRow:
    """The attempt :class:`TaskTokenGuard` authenticated for this request."""

    task: TaskRow = getattr(request.state, TASK_STATE_KEY)
    return task


def _live(request: Request, task: TaskRow) -> TaskContext | None:
    """The live context of ``task``, or ``None`` if it is not running here."""

    return agent.maybe_live(request, task.id)


# --------------------------------------------------------------------------
# Listing the tools
# --------------------------------------------------------------------------


def _submit_schema(live: TaskContext | None) -> dict[str, Any]:
    """``submit_result``'s input schema: the declared model's, or a free object.

    05 §Tooling tiers: "``submit_result``'s input schema **is** the
    node's ``output_model`` schema, so the model sees it as a tool
    definition". Read here rather than cached, because the façade
    declares it on the context when it starts the turn and the listing is
    per request.
    """

    model = None if live is None else live.output_model
    return FREE_OBJECT if model is None else model.model_json_schema()


def _tools(live: TaskContext | None) -> list[Tool]:
    """The tools this attempt may call, in the order 19 names them.

    ``ask_operator`` is here only with ``ask_policy == "http"``: the
    prompt drops its instructions in that case too (19 §Assembly), so a
    model is never told about a tool it is not offered. ``wait_answer``
    goes with it — there is nothing to wait for when nothing can be
    asked.
    """

    tools = [
        Tool(
            name="get_task",
            description=GET_TASK_DESCRIPTION,
            input_schema=NoArgs.model_json_schema(),
        ),
        Tool(
            name="append_log",
            description=APPEND_LOG_DESCRIPTION,
            input_schema=LogText.model_json_schema(),
        ),
        Tool(
            name="submit_result",
            description=SUBMIT_RESULT_DESCRIPTION,
            input_schema=_submit_schema(live),
        ),
    ]
    if live is not None and live.ask_policy == "http":
        tools.append(
            Tool(
                name="ask_operator",
                description=ASK_OPERATOR_DESCRIPTION,
                input_schema=AskArgs.model_json_schema(),
            )
        )
        tools.append(
            Tool(
                name="wait_answer",
                description=WAIT_ANSWER_DESCRIPTION,
                input_schema=WaitArgs.model_json_schema(),
            )
        )
    return tools


# --------------------------------------------------------------------------
# Calling them
# --------------------------------------------------------------------------


def _result(body: dict[str, Any], *, is_error: bool = False) -> CallToolResult:
    """One tool result, said twice: as structured content and as text.

    A harness that understands ``structuredContent`` reads the object; a
    model that only sees text reads the same object pretty-printed. 08
    §Conventions' ``default=str`` is used for the text half for the same
    reason the API uses it — the extras of a rejection carry whatever a
    validator produced, and a result that failed to render would be worse
    than one that rendered a value as its repr.
    """

    text = json.dumps(body, indent=2, default=str)
    return CallToolResult(
        content=[TextContent(type="text", text=text)],
        structured_content=body,
        is_error=is_error,
    )


def _refusal(error: ApiError) -> CallToolResult:
    """A refusal, as the error body of 08 §Conventions with ``isError`` set."""

    return _result(error.body, is_error=True)


_ArgsT = TypeVar("_ArgsT", bound=BaseModel)


def _parse(model: type[_ArgsT], args: dict[str, Any]) -> _ArgsT:
    """``args`` as ``model``, or the 422 the REST route would have given.

    The tools take the same bodies the routes take, so arguments that do
    not fit are the same refusal: 08 §Conventions' ``validation``, with
    the three fields of
    :func:`~athanore.api.errors.validation_error_handler` — the ones the
    SPA renders and a model can act on — rather than pydantic's full
    error dicts or the protocol's bare "invalid params".
    """

    try:
        return model.model_validate(args)
    except ValidationError as invalid:
        errors = [
            {
                "loc": list(error.get("loc", ())),
                "msg": error.get("msg", ""),
                "type": error.get("type", ""),
            }
            for error in invalid.errors()
        ]
        raise ApiError(
            422, ErrorCode.validation, "validation failed", errors=errors
        ) from invalid


async def _get_task(request: Request, task: TaskRow, args: dict[str, Any]) -> Any:
    _parse(NoArgs, args)
    return (await agent.get_task(request, task.id, task)).model_dump(mode="json")


async def _append_log(request: Request, task: TaskRow, args: dict[str, Any]) -> Any:
    written = await agent.append_log(request, task.id, task, _parse(LogText, args))
    return written.model_dump(mode="json")


async def _submit_result(request: Request, task: TaskRow, args: dict[str, Any]) -> Any:
    """``{ok: true}``, or the misfit the model can fix inside this turn.

    08 §MCP: a rejected submission comes back as ``{ok: false, errors,
    schema}`` with ``isError`` set, rather than as a protocol error, so
    the model reads the validator's complaint and the schema it failed
    against and calls the tool again — which is the whole reason the
    ``mcp`` tier exists (05 §Tooling tiers). Nothing is stored, and the
    rejection is on the context for 19's repair turn either way.
    """

    try:
        await agent.submit(request, task.id, task, payload=args)
    except ApiError as refusal:
        if refusal.code is not ErrorCode.validation:
            raise
        return _result({"ok": False, **refusal.extras}, is_error=True)
    return {"ok": True}


async def _ask_operator(request: Request, task: TaskRow, args: dict[str, Any]) -> Any:
    """Open a question, and optionally wait for its answer in the same call."""

    parsed = _parse(AskArgs, args)
    # `AskArgs` *is* an `Ask` — the wait is the only thing it adds — so
    # the route is handed the very body it would have parsed itself.
    opened = await agent.ask(request, task.id, task, parsed)
    answer = {"request_id": opened.request_id, "mode": opened.mode.value}
    if parsed.wait <= 0.0:
        return {**answer, "answered": False}
    poll = await agent.poll_request(
        request, task.id, task, opened.request_id, parsed.wait
    )
    if not poll.answered:
        return {**answer, "answered": False}
    return {**answer, "answered": True, "answer": poll.answer}


async def _wait_answer(request: Request, task: TaskRow, args: dict[str, Any]) -> Any:
    """The answer to a question this task asked, waiting up to ``wait`` for it."""

    parsed = _parse(WaitArgs, args)
    poll = await agent.poll_request(
        request, task.id, task, parsed.request_id, parsed.wait
    )
    if not poll.answered:
        return {"request_id": poll.request_id, "answered": False}
    return {
        "request_id": poll.request_id,
        "answered": True,
        "answer": poll.answer,
        "answered_by": None if poll.answered_by is None else poll.answered_by.value,
    }


#: Tool name → the coroutine that runs it. Every entry is a call into
#: :mod:`athanore.api.routers.agent`: the tools are the routes, reached
#: by another wire (08 §MCP).
TOOLS: Final = {
    "get_task": _get_task,
    "append_log": _append_log,
    "submit_result": _submit_result,
    "ask_operator": _ask_operator,
    "wait_answer": _wait_answer,
}


# --------------------------------------------------------------------------
# The server
# --------------------------------------------------------------------------


async def _on_list_tools(
    ctx: ServerRequestContext[Any, Any], params: PaginatedRequestParams | None
) -> ListToolsResult:
    """The tools of *this* attempt (08 §MCP)."""

    request = _request(ctx)
    task = _task(request)
    return ListToolsResult(tools=_tools(_live(request, task)))


async def _on_call_tool(
    ctx: ServerRequestContext[Any, Any], params: CallToolRequestParams
) -> CallToolResult:
    """Run one tool, and report a refusal the way a model can read it.

    Every failure the API has a word for — a task that is not running
    here, an agent that may not ask, a body that does not parse — comes
    back as an ``isError`` result carrying 08 §Conventions' error body.
    Anything else is a defect rather than a refusal, and is left to the
    protocol to report as an internal error, exactly as an unmapped
    exception is left to become a 500 on the REST side.
    """

    request = _request(ctx)
    task = _task(request)
    run = TOOLS.get(params.name)
    if run is None:
        return _refusal(
            ApiError(404, ErrorCode.not_found, f"no tool named {params.name!r}")
        )
    try:
        result = await run(request, task, params.arguments or {})
    except ApiError as refusal:
        return _refusal(refusal)
    except Exception as exc:
        mapped = api_error_for(exc)
        if mapped is None:
            raise
        return _refusal(mapped)
    if isinstance(result, CallToolResult):
        return result
    return _result(result)


def server() -> Server[Any]:
    """The MCP server: two handlers, and no state of its own.

    Everything that varies — the tools, their schemas, what they may do —
    is read per request from the attempt the token names, so one server
    object serves every agent this process is running.
    """

    return Server(
        SERVER_NAME,
        version=VERSION,
        title="Athanore",
        instructions="The task you were dispatched for. Read it with get_task, "
        "append your deliverable with append_log, and submit your structured "
        "result with submit_result.",
        on_list_tools=_on_list_tools,
        on_call_tool=_on_call_tool,
    )


#: The OpenAPI path item for the endpoint: opaque, tagged ``agent`` (08
#: §MCP). The document records that the route exists and what
#: authenticates it; the bodies are MCP's own JSON-RPC and are not
#: described here, because a generated client has no business calling
#: them — the SPA never does, and an agent speaks MCP with an MCP client.
PATH_ITEM: Final[dict[str, Any]] = {
    "post": {
        "tags": ["agent"],
        "summary": "Model Context Protocol server (streamable HTTP)",
        "description": (
            "The agent surface as MCP tools: `get_task`, `append_log`, "
            "`submit_result`, and — when the attempt's `ask_policy` is "
            "`http` — `ask_operator` and `wait_answer`. Authenticated by "
            "the same `X-Athanore-Token` header as `/api/agent/`; the task "
            "is the token's, so no tool takes a task id. The request and "
            "response bodies are MCP's own JSON-RPC and are opaque to this "
            "document."
        ),
        "operationId": "mcp_agent",
        "parameters": [
            {
                "name": TOKEN_HEADER,
                "in": "header",
                "required": True,
                "description": "The task token, from the claimed attempt.",
                "schema": {"type": "string"},
            }
        ],
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": {}}},
        },
        "responses": {
            "200": {
                "description": "One MCP response, as JSON or as an SSE stream.",
                "content": {
                    "application/json": {"schema": {}},
                    "text/event-stream": {"schema": {"type": "string"}},
                },
            },
            "403": {
                "description": "The task token is not valid for a live attempt.",
                "content": {
                    "application/json": {
                        # 08 §Conventions' error shape, written out rather
                        # than referenced: this module adds no component to
                        # the document, and the two keys are the whole of
                        # what a refusal here carries.
                        "schema": {
                            "type": "object",
                            "properties": {
                                "error": {"type": "string"},
                                "code": {"type": "string"},
                            },
                            "required": ["error", "code"],
                        }
                    }
                },
            },
        },
    }
}


def _document(app: FastAPI) -> None:
    """Add :data:`PATH_ITEM` to the application's OpenAPI document.

    The endpoint is a mounted ASGI application rather than a FastAPI
    route, so the generator does not see it; without this the snapshot
    would say the agent surface is five routes when it is five routes and
    a tool server. Wrapping ``app.openapi`` is FastAPI's own seam for
    exactly this, and the insertion is idempotent because the generator
    caches its document.
    """

    generate = app.openapi

    def openapi() -> dict[str, Any]:
        document = generate()
        document.setdefault("paths", {}).setdefault(MCP_PATH, PATH_ITEM)
        return document

    app.openapi = openapi  # pyright: ignore[reportAttributeAccessIssue]


def mount(app: FastAPI, settings: AthanoreSettings) -> StreamableHTTPSessionManager:
    """Mount the MCP server on ``app`` at :data:`MCP_PATH`.

    Returns the session manager, which the application's lifespan must
    run: it owns the task group every request's server instance is
    started in, so nothing is served until it is entered.

    The route is a plain Starlette :class:`~starlette.routing.Route` with
    an ASGI endpoint rather than a mount, so the path is exact — a mount
    would answer ``/mcp/agent/anything`` and redirect the bare path — and
    so the request the tools read is the one the guard authenticated.
    """

    manager = StreamableHTTPSessionManager(
        app=server(),
        stateless=True,
        # Athanore's posture is 12's: loopback by default, and a task
        # token on every request whatever the bind. The SDK's Host and
        # Origin checks would additionally pin the endpoint to the host
        # it was configured with, which `public_url` already decides.
        security_settings=None,
        max_request_body_size=settings.body_limit,
    )
    app.router.routes.append(
        Route(MCP_PATH, endpoint=TaskTokenGuard(StreamableHTTPASGIApp(manager)))
    )
    _document(app)
    return manager

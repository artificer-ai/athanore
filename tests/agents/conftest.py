"""A store, and one attempt's :class:`TaskContext` over it.

The agent suite's subject is the façade, not the engine: nothing here
runs a scheduler, claims a task or holds a pool slot. What a façade needs
is a context — the ids that go into 19's kickoff, the token that goes
into its curl lines, and ``services`` for the one read the prompt makes
(the run's title, 04 §TaskContext).

The store is real rather than a stub for that read. A fake ``run.get()``
would let the title be anything, and the thing worth asserting is that
the title in the prompt is the title of the run the operator submitted.
It is a file on ``tmp_path`` and SQLite only, for the reason
``tests/engine/conftest.py`` gives: the backend matrix belongs to the
suite that owns the SQL.

A conftest rather than imports because ``tests`` is not a package, so a
helper shared between this suite's modules arrives through pytest or not
at all (D112).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.applications import Starlette

from athanore.agents.submissions import validate_submission
from athanore.engine.context import TaskContext
from athanore.engine.services import TaskRequests, TaskServices
from athanore.events.bus import EventBus
from athanore.requests.service import RequestService
from athanore.store.engine import make_engine
from athanore.store.tables import metadata
from athanore.store.uow import Store

#: One transcript chunk, as this suite reads it back: kind and text.
Chunk = tuple[str, str]

#: Where the ``mcp`` tier's tool server lives (05 §Tooling tiers). The
#: façade builds this URL from ``ctx.api_base``; T045a mounts the real
#: one there.
MCP_MOUNT = "/mcp/agent"

#: What ``settings.public_url`` is in these tests: the loopback bind an
#: agent on the same machine is told to call (08 §Agent).
API_BASE = "http://127.0.0.1:4002"

#: A task token, clear text. Distinctive enough that a test can look for
#: it anywhere in a rendered prompt and mean it.
TOKEN = "tok-fdb0a1c2e3f4"

WORKFLOW = "demo"
NODE = "build"
FLUSH_INTERVAL = 0.05


@pytest.fixture
def bus() -> EventBus:
    """The bus the store publishes to. Nothing here subscribes to it."""

    return EventBus()


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    """This test's database, named once.

    Exposed rather than inlined below because the suite that drives whole
    runs through a real ``Engine`` (``test_stats_workflow.py``) has to
    build an :class:`~athanore.settings.AthanoreSettings` pointing at the
    same file the store is on.
    """

    return f"sqlite+aiosqlite:///{tmp_path / 'athanore.db'}"


@pytest.fixture
async def store(db_url: str, bus: EventBus) -> AsyncIterator[Store]:
    """A store on an empty SQLite file."""

    engine = make_engine(db_url)
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    try:
        yield Store(engine, bus)
    finally:
        await engine.dispose()


@pytest.fixture
def context(store: Store) -> Callable[..., Awaitable[TaskContext]]:
    """Make the context of one attempt of a real run's one task.

    The run and the task are rows: the prompt reads the run back through
    ``services.run.get()``, and a context pointing at a run that does not
    exist would be a fixture that only ever tested the failure.
    """

    async def make(
        title: str = "a run",
        *,
        node: str = NODE,
        api_base: str = API_BASE,
        token: str = TOKEN,
    ) -> TaskContext:
        async with store.uow() as uow:
            run = await uow.runs.insert(WORKFLOW, title)
            task = await uow.tasks.enqueue(
                run.id, node, None, priority=0, explicit=False
            )
        return TaskContext(
            run_id=run.id,
            task_id=task.id,
            workflow=WORKFLOW,
            node=node,
            attempt=1,
            token=token,
            api_base=api_base,
            services=TaskServices(
                store,
                run_id=run.id,
                task_id=task.id,
                node=node,
                workflow=WORKFLOW,
                flush_interval=FLUSH_INTERVAL,
            ),
        )

    return make


@pytest.fixture
def claimed_context(
    store: Store, request_service: RequestService
) -> Callable[..., Awaitable[TaskContext]]:
    """The context of one **claimed** attempt, with its request port wired.

    What the ``ask`` policies need and :func:`context` deliberately does
    not have: a request is answerable only while its task is
    ``in_progress`` or ``waiting`` (06 §The model), and it is opened
    against a port a service is behind. Two fixtures rather than one
    because most of this suite is about a façade and not about a
    question — a wired port on every context would make every test pay
    for a service it never asks anything of.
    """

    async def make(
        title: str = "a run",
        *,
        node: str = NODE,
        api_base: str = API_BASE,
        token: str = TOKEN,
    ) -> TaskContext:
        async with store.uow() as uow:
            run = await uow.runs.insert(WORKFLOW, title)
            task = await uow.tasks.enqueue(
                run.id, node, None, priority=0, explicit=False
            )
            await uow.tasks.claim_ready(1, [WORKFLOW])
        port = TaskRequests(request_service, run_id=run.id, task_id=task.id)
        ctx = TaskContext(
            run_id=run.id,
            task_id=task.id,
            workflow=WORKFLOW,
            node=node,
            attempt=1,
            token=token,
            api_base=api_base,
            services=TaskServices(
                store,
                run_id=run.id,
                task_id=task.id,
                node=node,
                workflow=WORKFLOW,
                flush_interval=FLUSH_INTERVAL,
                requests=port,
            ),
        )
        port.attach(ctx)
        return ctx

    return make


@pytest.fixture
def request_service(store: Store, bus: EventBus) -> RequestService:
    """The one request service a host builds beside its engine (T031)."""

    return RequestService(store, bus)


@pytest.fixture
def transcript(store: Store) -> Callable[[TaskContext], Awaitable[list[Chunk]]]:
    """Read one task's agent transcript, as ``(kind, text)`` in order.

    A read of the rows rather than of the service's buffer: the point of
    a transcript assertion is that the chunk was *written*, and the
    flusher is what writes it. A fixture rather than a helper because
    ``tests`` is not a package — anything shared between this suite's
    modules arrives through pytest or not at all (D112).
    """

    async def read(ctx: TaskContext) -> list[Chunk]:
        async with store.reader() as reader:
            return [
                (str(chunk.kind), chunk.text)
                for chunk in await reader.stream.list_after(ctx.task_id)
            ]

    return read


@pytest.fixture
def work_log(store: Store) -> Callable[[TaskContext], Awaitable[list[str]]]:
    """Read one run's work-log entries, oldest first."""

    async def read(ctx: TaskContext) -> list[str]:
        async with store.reader() as reader:
            return [entry.text for entry in await reader.log.list(ctx.run_id)]

    return read


@pytest.fixture
def stats_lines(
    work_log: Callable[[TaskContext], Awaitable[list[str]]],
) -> Callable[[TaskContext], Awaitable[list[str]]]:
    """The ``[stats]`` lines of one run: one per agent run, and no more.

    The assertion this exists for is a *count*. 05 §Stats entry records
    one entry per ``run()`` on every exit path, and "exactly once" is the
    half of that which a ``finally`` gets wrong.
    """

    async def read(ctx: TaskContext) -> list[str]:
        return [text for text in await work_log(ctx) if text.startswith("[stats]")]

    return read


# --------------------------------------------------------------------------
# The agent API a real subprocess posts to
# --------------------------------------------------------------------------


class AgentAPI:
    """The two agent endpoints of 08 that a scripted fake actually calls.

    ``FakeACPAgent`` reads ``$ATHANORE_TASK_URL`` and POSTs its ``log``
    and its ``submit`` over HTTP (13 §Fakes, D122), so a façade test with
    an ``output_model`` needs something listening: without it every run
    ends in ``no_submission`` and the repair loop is the only thing the
    suite can see.

    :mod:`athanore.api.routers.agent` is the real thing, and it needs an
    engine with the attempt registered on its live registry; this suite
    builds a context and no engine, because its subject is the façade.
    So this is the same path one layer down —
    :func:`~athanore.agents.submissions.validate_submission`, then
    ``services.submissions.accept`` or ``reject`` plus
    ``ctx.last_rejection`` — which is what the endpoint does above it and
    what ``tests/api/test_agent_api.py`` tests it doing. What this
    fixture is faithful about is what the fake depends on: the paths, the
    ``X-Athanore-Token`` header, and the 422 that drives a repair turn.
    """

    def __init__(self) -> None:
        self.base = ""
        self.ctx: TaskContext | None = None
        #: Every token that reached the HTTP endpoints, in order.
        self.tokens: list[str] = []
        #: Every token that reached the MCP mount, in order.
        self.mcp_tokens: list[str] = []

    async def post(self, path: str, payload: Any) -> str:
        """POST to this task's own agent endpoint, as an adapter would."""

        ctx = self.ctx
        if ctx is None:  # pragma: no cover - a test that forgot to attach
            raise AssertionError("no task attached to the agent API")
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self.base}/api/agent/tasks/{ctx.task_id}/{path}",
                json=payload,
                headers={"X-Athanore-Token": ctx.token},
            )
        return f"{path}: {response.status_code}"

    def attach(self, ctx: TaskContext) -> None:
        """Serve this attempt. One at a time, like the real endpoint."""

        self.ctx = ctx

    def _task(self, token: str) -> TaskContext:
        self.tokens.append(token)
        if self.ctx is None:  # pragma: no cover - a test that forgot to attach
            raise AssertionError("no task attached to the agent API")
        if token != self.ctx.token:
            raise PermissionError(token)
        return self.ctx


@pytest.fixture
async def agent_api() -> AsyncIterator[AgentAPI]:
    """One server carrying both substrates of 05 §Tooling tiers.

    ``/api/agent/tasks/{id}/log`` and ``/submit`` are what the ``http``
    tier's curl lines reach and what ``FakeACPAgent`` POSTs to.
    ``/mcp/agent`` is the tool server the ``mcp`` tier hands to
    ``session/new`` (T045a mounts the real one), and **its tools call those
    same endpoints over HTTP** — which is what 05 means by "all three sit
    on the agent HTTP API of 08, which stays the single substrate".
    """

    state = AgentAPI()
    app = FastAPI()

    @app.post("/api/agent/tasks/{task_id}/log")
    async def append_log(task_id: int, request: Request) -> JSONResponse:
        try:
            ctx = state._task(request.headers.get("X-Athanore-Token", ""))
        except PermissionError:
            return JSONResponse({"error": "forbidden"}, status_code=403)
        body = await request.json()
        row = await ctx.services.log.append(body["text"], author="agent")
        return JSONResponse({"id": row.id})

    @app.post("/api/agent/tasks/{task_id}/submit")
    async def submit(task_id: int, request: Request) -> JSONResponse:
        try:
            ctx = state._task(request.headers.get("X-Athanore-Token", ""))
        except PermissionError:
            return JSONResponse({"error": "forbidden"}, status_code=403)
        payload = await request.json()
        ok, errors, _value = validate_submission(ctx.output_model, payload)
        if ok:
            row = await ctx.services.submissions.accept(payload)
            return JSONResponse({"id": row.id})
        model = ctx.output_model
        schema = {} if model is None else model.model_json_schema()
        ctx.last_rejection = {
            **await ctx.services.submissions.reject(errors, schema),
            "payload": payload,
        }
        return JSONResponse({"errors": errors, "schema": schema}, status_code=422)

    server_app = _mcp_app(state)
    app.router.routes.extend(server_app.routes)
    app.add_middleware(_TokenRecorder, state=state)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        """The MCP session manager's task group, on the app that carries it."""

        async with server_app.router.lifespan_context(server_app):
            yield

    app.router.lifespan_context = lifespan

    with _uvicorn_logging_restored():
        served, task, port = await _serve(app)
        state.base = f"http://127.0.0.1:{port}"
        try:
            yield state
        finally:
            served.should_exit = True
            await asyncio.wait_for(task, timeout=10)


def _mcp_app(state: AgentAPI) -> Starlette:
    """The ``athanore`` tool server, at ``/mcp/agent`` (05 §Tooling tiers).

    Two of the five tools of 08 §MCP — the two ``mcp_calls`` exercises —
    and each one is an HTTP call to the endpoint above rather than a
    store write, because the tier is an adapter over the one wire
    contract and a fixture that wrote rows directly would prove nothing
    about that.

    The token it calls with is the attached task's rather than the one on
    the incoming MCP request: reading a header from inside a streamable
    HTTP tool call means reaching into the session manager's task group,
    and the assertion that matters — *the header arrived* — is
    :attr:`AgentAPI.mcp_tokens`, recorded by the wrapper below.
    """

    from mcp.server.mcpserver import MCPServer

    server: Any = MCPServer(name="athanore")

    @server.tool()
    async def append_log(text: str) -> str:
        """Append one line to the run's work log."""

        return await state.post("log", {"text": text})

    @server.tool()
    async def submit_result(payload: dict[str, Any]) -> str:
        """Submit the structured result for this task."""

        return await state.post("submit", payload)

    return server.streamable_http_app(streamable_http_path=MCP_MOUNT)


class _TokenRecorder:
    """Record the ``X-Athanore-Token`` of every MCP request that arrives.

    The ``mcp`` tier's whole claim is that the token travels in the
    server's header instead of in the prompt, so the assertion has to be
    over what actually reached the server — a header on the wire, not a
    value the fixture passed itself.
    """

    def __init__(self, app: Any, state: AgentAPI) -> None:
        self._app = app
        self._state = state

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "http" and scope["path"].startswith(MCP_MOUNT):
            headers = {key.decode(): value.decode() for key, value in scope["headers"]}
            self._state.mcp_tokens.append(headers.get("x-athanore-token", ""))
        await self._app(scope, receive, send)


@contextmanager
def _uvicorn_logging_restored() -> Iterator[None]:
    """Put the ``uvicorn.*`` loggers back the way they were found.

    ``uvicorn.Config`` configures logging **globally** — a level on
    ``uvicorn.error``, handlers on ``uvicorn.access`` — and this suite
    starts a server per test. Left alone it would leak into whatever ran
    next, which is how a server fixture over here breaks an assertion
    about ``configure_logging`` over there.
    """

    names = ("uvicorn", "uvicorn.error", "uvicorn.access", "uvicorn.asgi")
    before = [
        (logger, logger.level, list(logger.handlers), logger.propagate)
        for logger in (logging.getLogger(name) for name in names)
    ]
    try:
        yield
    finally:
        for logger, level, handlers, propagate in before:
            logger.setLevel(level)
            logger.handlers = handlers
            logger.propagate = propagate


async def _serve(app: Any) -> tuple[uvicorn.Server, asyncio.Task[None], int]:
    """Serve ``app`` on a free loopback port; a subprocess reaches it by URL."""

    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=0,
            log_level="warning",
            log_config=None,
            lifespan="on",
        )
    )
    task = asyncio.get_running_loop().create_task(server.serve())
    while not server.started:  # noqa: ASYNC110 - uvicorn signals with a flag
        await asyncio.sleep(0.01)
    return server, task, server.servers[0].sockets[0].getsockname()[1]


@pytest.fixture
def served_context(
    agent_api: AgentAPI, context: Callable[..., Awaitable[TaskContext]]
) -> Callable[..., Awaitable[TaskContext]]:
    """A :func:`context` whose ``api_base`` is a listening agent API.

    What a façade test with an ``output_model`` needs, because the agent
    is a real process and it submits over HTTP.
    """

    async def make(*args: Any, **kwargs: Any) -> TaskContext:
        kwargs.setdefault("api_base", agent_api.base)
        ctx = await context(*args, **kwargs)
        agent_api.attach(ctx)
        return ctx

    return make

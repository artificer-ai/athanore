"""``/mcp/agent``: the agent surface as MCP tools (T045a, 08 §MCP).

Driven by the `mcp` Python client over `httpx2.ASGITransport`, so the
whole stack the tier really uses is under test: the streamable-HTTP
transport, the token guard in front of it, the per-request tool listing,
and the routes of `athanore/api/routers/agent.py` the tools call.
(`httpx2` is the HTTP client `mcp` itself speaks through, so it is here
wherever the MCP client is; the application is still served to the
operator's `httpx` client, which is what `tests/api/conftest.py` builds.)

The attempt is claimed and registered the way `test_agent_api.py` claims
one and for the same reason — a task token is minted at claim and is live
only while the attempt is (12 §Task tokens), and the tools that write
need the attempt's live `TaskContext`.

The suite's own rule: **nothing here may be reachable that is not
reachable through `/api/agent/`**. Where a tool has an HTTP twin the test
asserts the two agree rather than asserting the tool alone.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from typing import Any, Literal

import httpx
import httpx2
import pytest
from fastapi import FastAPI
from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import MCPError
from mcp.types import CallToolResult, Tool
from pydantic import BaseModel

from athanore.api import mcp
from athanore.engine import Engine
from athanore.engine.context import TaskContext
from athanore.engine.pools import Pool
from athanore.engine.services import TaskRequests, TaskServices
from athanore.events.bus import EventBus
from athanore.requests.service import RequestService
from athanore.settings import AthanoreSettings
from athanore.store.rows import LogAuthor, RequestSource
from athanore.store.uow import Store
from athanore.workflow import Workflow

#: The specification of the tool descriptions. Read, not remembered.
DOC = Path(__file__).parents[2] / "docs" / "v1" / "19-agent-prompts.md"

NODE = "review"
FLUSH_INTERVAL = 0.02
URL = f"http://testserver{mcp.MCP_PATH}"


# --------------------------------------------------------------------------
# The workflow, and the model an agent is asked for
# --------------------------------------------------------------------------

demo = Workflow("demo")


@demo.node(start=True)
async def review(ship: Any) -> None:
    """The one node these attempts are of."""


@demo.node()
async def ship() -> None:
    """Where it goes next."""


class Review(BaseModel):
    """What a reviewer must submit (05 §Submissions)."""

    verdict: Literal["approve", "changes_requested"]
    feedback: str = ""


# --------------------------------------------------------------------------
# The application, with a request service behind it
# --------------------------------------------------------------------------


@pytest.fixture
def request_service(store: Store, bus: EventBus) -> RequestService:
    return RequestService(store, bus)


@pytest.fixture
def engine(
    settings: AthanoreSettings,
    store: Store,
    bus: EventBus,
    request_service: RequestService,
) -> Engine:
    """`tests/api/conftest.py`'s engine, wired to a request service."""

    engine = Engine(settings, store, bus, requests=request_service)
    engine.register(demo.finalize(), Pool("agent_pool", capacity=2))
    return engine


# --------------------------------------------------------------------------
# One claimed, live attempt
# --------------------------------------------------------------------------


class Attempt:
    """A claimed attempt, its live context, and the token it is reached by."""

    def __init__(self, ctx: TaskContext) -> None:
        self.ctx = ctx
        self.task_id = ctx.task_id
        self.run_id = ctx.run_id
        self.token = ctx.token
        self.base = f"/api/agent/tasks/{ctx.task_id}"
        self.headers = {"X-Athanore-Token": ctx.token}


Claim = Callable[..., Awaitable[Attempt]]


@pytest.fixture
def attempt(store: Store, engine: Engine, request_service: RequestService) -> Claim:
    """Claim a task and register its context, the way the runner does."""

    async def make(
        title: str = "ship it",
        description: str = "the brief",
        *,
        payload: Any = None,
    ) -> Attempt:
        async with store.uow() as uow:
            run = await uow.runs.insert("demo", title, description)
            task = await uow.tasks.enqueue(
                run.id, NODE, payload, priority=0, explicit=False
            )
            claimed = await uow.tasks.claim_ready(1, ["demo"])
        assert [one.task.id for one in claimed] == [task.id]
        port = TaskRequests(request_service, run_id=run.id, task_id=task.id)
        ctx = TaskContext(
            run_id=run.id,
            task_id=task.id,
            workflow="demo",
            node=NODE,
            attempt=task.attempt,
            token=claimed[0].token,
            api_base="http://127.0.0.1:4002",
            services=TaskServices(
                store,
                run_id=run.id,
                task_id=task.id,
                node=NODE,
                workflow="demo",
                flush_interval=FLUSH_INTERVAL,
                requests=port,
            ),
        )
        port.attach(ctx)
        engine.live.register(ctx)
        return Attempt(ctx)

    return make


# --------------------------------------------------------------------------
# The MCP client
# --------------------------------------------------------------------------


Connect = Callable[[str], AbstractAsyncContextManager[Client]]


@asynccontextmanager
async def serving(app: FastAPI) -> AsyncIterator[Connect]:
    """Start ``app``, and hand back a way to connect an MCP client to it.

    The lifespan is entered here rather than in a fixture because it
    starts an anyio task group — the MCP session manager's — and a cancel
    scope must be exited by the task that entered it, which a fixture's
    separate setup and teardown steps cannot promise. It is entered once
    per application because that is what a lifespan is: the manager
    refuses a second `run()`, exactly as a server would never start one.

    The factory it yields is what takes the token, so one running
    application can be spoken to by two agents — which is how a test asks
    whether one token reaches the other's request.
    """

    async with app.router.lifespan_context(app):

        @asynccontextmanager
        async def connect(token: str) -> AsyncIterator[Client]:
            """One MCP client, speaking streamable HTTP over ASGI.

            ``cache=None`` turns off the client's own ``tools/list``
            cache: the listing is per attempt and changes with what the
            façade declares, and a test that changed it wants to see the
            change rather than the answer from before.
            """

            async with httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=app),
                base_url="http://testserver",
                headers={mcp.TOKEN_HEADER: token},
                follow_redirects=True,
            ) as http:
                transport = streamable_http_client(URL, http_client=http)
                async with Client(transport, cache=None) as client:
                    yield client

        yield connect


def tools(listed: list[Tool]) -> dict[str, Tool]:
    return {tool.name: tool for tool in listed}


def body(result: CallToolResult) -> Any:
    """The one object a tool result carries, read back both ways.

    Every result of this server says the same thing twice — as
    ``structuredContent`` for a harness that parses it and as JSON text
    for a model that only reads text — so a test that checked one and not
    the other would not be checking the tool's answer.
    """

    assert len(result.content) == 1
    first = result.content[0]
    assert first.type == "text"
    assert json.loads(first.text) == result.structured_content
    return result.structured_content


# --------------------------------------------------------------------------
# The tool list
# --------------------------------------------------------------------------


async def test_the_five_tools_of_08_are_offered(app: FastAPI, attempt: Claim) -> None:
    """08 §MCP's table, and nothing beside it."""

    live = await attempt()
    live.ctx.ask_policy = "http"
    async with serving(app) as connect, connect(live.token) as client:
        listed = tools((await client.list_tools()).tools)
    assert list(listed) == [
        "get_task",
        "append_log",
        "submit_result",
        "ask_operator",
        "wait_answer",
    ]


async def test_no_tool_takes_a_task_id(app: FastAPI, attempt: Claim) -> None:
    """The task is the token's: there is no id for a tool to name (08 §MCP)."""

    live = await attempt()
    live.ctx.ask_policy = "http"
    async with serving(app) as connect, connect(live.token) as client:
        listed = (await client.list_tools()).tools
    for tool in listed:
        named = set(tool.input_schema.get("properties", {}))
        assert not named & {"task_id", "task", "id", "token"}, tool.name


async def test_submit_result_declares_the_nodes_output_model(
    app: FastAPI, attempt: Claim
) -> None:
    """05 §Tooling tiers: the tool's input schema *is* the model's."""

    live = await attempt()
    live.ctx.output_model = Review
    async with serving(app) as connect, connect(live.token) as client:
        listed = tools((await client.list_tools()).tools)
    assert listed["submit_result"].input_schema == Review.model_json_schema()
    assert "verdict" in listed["submit_result"].input_schema["properties"]


async def test_submit_result_takes_any_object_when_no_model_is_declared(
    app: FastAPI, attempt: Claim
) -> None:
    live = await attempt()
    assert live.ctx.output_model is None
    async with serving(app) as connect, connect(live.token) as client:
        listed = tools((await client.list_tools()).tools)
    assert listed["submit_result"].input_schema == mcp.FREE_OBJECT


async def test_the_listing_is_read_when_it_is_asked_for(
    app: FastAPI, attempt: Claim
) -> None:
    """The façade declares the model on the context; the list follows it."""

    live = await attempt()
    async with serving(app) as connect, connect(live.token) as client:
        before = tools((await client.list_tools()).tools)
        live.ctx.output_model = Review
        after = tools((await client.list_tools()).tools)
    assert before["submit_result"].input_schema == mcp.FREE_OBJECT
    assert after["submit_result"].input_schema == Review.model_json_schema()


async def test_ask_operator_is_absent_when_the_policy_is_off(
    app: FastAPI, attempt: Claim
) -> None:
    """Absence is the enforcement, matching `/ask`'s 403 (08 §MCP)."""

    live = await attempt()
    assert live.ctx.ask_policy == "off"
    async with serving(app) as connect, connect(live.token) as client:
        listed = tools((await client.list_tools()).tools)
    assert "ask_operator" not in listed
    assert "wait_answer" not in listed
    assert set(listed) == {"get_task", "append_log", "submit_result"}


async def test_calling_ask_operator_anyway_is_refused(
    app: FastAPI, attempt: Claim, store: Store
) -> None:
    """A model that went looking gets `/ask`'s 403, as a tool result."""

    live = await attempt()
    async with serving(app) as connect, connect(live.token) as client:
        result = await client.call_tool("ask_operator", {"prompt": "which branch?"})
    assert result.is_error
    refusal = body(result)
    assert refusal["code"] == "forbidden"
    assert "ask_policy" in refusal["error"]
    async with store.reader() as reader:
        assert await reader.requests.list_views(live.run_id) == []


async def test_an_unknown_tool_is_refused_rather_than_crashing(
    app: FastAPI, attempt: Claim
) -> None:
    live = await attempt()
    async with serving(app) as connect, connect(live.token) as client:
        result = await client.call_tool("delete_everything", {})
    assert result.is_error
    assert body(result)["code"] == "not_found"


# --------------------------------------------------------------------------
# The descriptions
# --------------------------------------------------------------------------


def flat(text: str) -> str:
    """``text`` with every run of whitespace collapsed to one space.

    19 states one of these sentences inside a paragraph rather than a
    fenced block, so it is wrapped where the line ended rather than where
    the sentence did. The words are the contract; where the document
    broke them is not.
    """

    return " ".join(text.split())


def test_every_tool_description_is_19s_wording() -> None:
    """08 §MCP: the tool list and the prompt say the same thing."""

    text = flat(DOC.read_text(encoding="utf-8"))
    descriptions = {
        "get_task": mcp.GET_TASK_DESCRIPTION,
        "append_log": mcp.APPEND_LOG_DESCRIPTION,
        "submit_result": mcp.SUBMIT_RESULT_DESCRIPTION,
        "ask_operator": mcp.ASK_OPERATOR_DESCRIPTION,
        "wait_answer": mcp.WAIT_ANSWER_DESCRIPTION,
    }
    for name, description in descriptions.items():
        for line in description.split("\n"):
            assert flat(line) in text, f"{name}: 19 no longer says {line!r}"


async def test_the_tools_are_described_where_the_agent_reads_them(
    app: FastAPI, attempt: Claim
) -> None:
    live = await attempt()
    live.ctx.ask_policy = "http"
    async with serving(app) as connect, connect(live.token) as client:
        listed = tools((await client.list_tools()).tools)
    assert listed["get_task"].description == mcp.GET_TASK_DESCRIPTION
    assert listed["append_log"].description == mcp.APPEND_LOG_DESCRIPTION
    assert listed["submit_result"].description == mcp.SUBMIT_RESULT_DESCRIPTION
    assert listed["ask_operator"].description == mcp.ASK_OPERATOR_DESCRIPTION
    assert listed["wait_answer"].description == mcp.WAIT_ANSWER_DESCRIPTION


# --------------------------------------------------------------------------
# get_task
# --------------------------------------------------------------------------


async def test_get_task_is_the_body_the_rest_route_returns(
    app: FastAPI, client: httpx.AsyncClient, attempt: Claim, store: Store
) -> None:
    """One wire contract: the tool is the route, reached another way."""

    live = await attempt("ship it", "review the branch", payload={"branch": "feat/x"})
    live.ctx.output_model = Review
    async with store.uow() as uow:
        await uow.log.append(
            run_id=live.run_id,
            node=NODE,
            author=LogAuthor.agent,
            text="the previous stage's deliverable",
            task_id=live.task_id,
        )
    async with serving(app) as connect, connect(live.token) as mcp_client:
        result = await mcp_client.call_tool("get_task", {})
    read = body(result)
    assert not result.is_error
    assert read["task_id"] == live.task_id
    assert read["run_id"] == live.run_id
    assert read["node"] == NODE
    assert read["title"] == "ship it"
    assert read["input"] == {"branch": "feat/x"}
    assert read["output_schema"] == Review.model_json_schema()
    assert [entry["text"] for entry in read["log"]] == [
        "the previous stage's deliverable"
    ]
    rest = await client.get(live.base, headers=live.headers)
    assert rest.json() == read


# --------------------------------------------------------------------------
# append_log
# --------------------------------------------------------------------------


async def test_append_log_writes_the_entry_as_the_agent(
    app: FastAPI, attempt: Claim, store: Store
) -> None:
    """The deliverable of a stage, on the channel the next one reads (D4)."""

    live = await attempt()
    async with serving(app) as connect, connect(live.token) as client:
        result = await client.call_tool("append_log", {"text": "reviewed it: approve"})
    written = body(result)
    assert not result.is_error
    async with store.reader() as reader:
        entries = await reader.log.list(live.run_id)
    assert [(one.id, one.author, one.node, one.task_id) for one in entries] == [
        (written["log_id"], LogAuthor.agent, NODE, live.task_id)
    ]
    assert entries[0].text == "reviewed it: approve"


async def test_a_blank_log_entry_is_refused(app: FastAPI, attempt: Claim) -> None:
    """`LogText` is the same body the route parses, so the same refusal."""

    live = await attempt()
    async with serving(app) as connect, connect(live.token) as client:
        result = await client.call_tool("append_log", {"text": "   "})
    assert result.is_error


# --------------------------------------------------------------------------
# submit_result
# --------------------------------------------------------------------------


async def test_a_fitting_submission_is_stored(
    app: FastAPI, attempt: Claim, store: Store
) -> None:
    live = await attempt()
    live.ctx.output_model = Review
    async with serving(app) as connect, connect(live.token) as client:
        result = await client.call_tool(
            "submit_result", {"verdict": "approve", "feedback": "ok"}
        )
    assert not result.is_error
    assert body(result) == {"ok": True}
    async with store.reader() as reader:
        row = await reader.submissions.latest(live.task_id)
        events = await reader.events.list_for_run(live.run_id)
    assert row is not None
    assert row.payload == {"verdict": "approve", "feedback": "ok"}
    assert [one.name for one in events].count("submission.accepted") == 1


async def test_a_submission_with_no_model_declared_is_stored_raw(
    app: FastAPI, attempt: Claim, store: Store
) -> None:
    live = await attempt()
    async with serving(app) as connect, connect(live.token) as client:
        result = await client.call_tool("submit_result", {"anything": [1, 2]})
    assert not result.is_error
    async with store.reader() as reader:
        row = await reader.submissions.latest(live.task_id)
    assert row is not None and row.payload == {"anything": [1, 2]}


async def test_a_misfit_is_the_errors_and_the_schema_in_the_tool_result(
    app: FastAPI, attempt: Claim, store: Store
) -> None:
    """08 §MCP: `{ok: false, errors, schema}` with `isError`, so the model
    fixes the shape inside the same turn (05 §Submissions)."""

    live = await attempt()
    live.ctx.output_model = Review
    async with serving(app) as connect, connect(live.token) as client:
        result = await client.call_tool("submit_result", {"verdict": "maybe"})
    assert result.is_error
    rejected = body(result)
    assert rejected["ok"] is False
    assert rejected["schema"] == Review.model_json_schema()
    assert [error["loc"] for error in rejected["errors"]] == [["verdict"]]
    async with store.reader() as reader:
        assert await reader.submissions.latest(live.task_id) is None
        names = [one.name for one in await reader.events.list_for_run(live.run_id)]
    assert names.count("submission.rejected") == 1
    # And it is on the context, for 19's repair turn to quote back (T035).
    assert live.ctx.last_rejection is not None
    assert live.ctx.last_rejection["payload"] == {"verdict": "maybe"}


async def test_a_rejected_submission_can_be_fixed_in_the_same_session(
    app: FastAPI, attempt: Claim, store: Store
) -> None:
    """The whole point of the tier: the misfit comes back as a result."""

    live = await attempt()
    live.ctx.output_model = Review
    async with serving(app) as connect, connect(live.token) as client:
        first = await client.call_tool("submit_result", {"verdict": "maybe"})
        second = await client.call_tool("submit_result", {"verdict": "approve"})
    assert first.is_error and not second.is_error
    async with store.reader() as reader:
        row = await reader.submissions.latest(live.task_id)
    assert row is not None and row.payload == {"verdict": "approve"}


async def test_a_submission_to_an_attempt_that_is_not_running_here_is_refused(
    app: FastAPI, attempt: Claim, engine: Engine
) -> None:
    """No live context is 08's "409 if the task is not in progress"."""

    live = await attempt()
    engine.live.unregister(live.task_id)
    async with serving(app) as connect, connect(live.token) as client:
        result = await client.call_tool("submit_result", {"a": 1})
    assert result.is_error
    assert body(result)["code"] == "conflict"


# --------------------------------------------------------------------------
# ask_operator and wait_answer
# --------------------------------------------------------------------------


async def test_ask_operator_opens_the_request_the_rest_route_would(
    app: FastAPI, attempt: Claim, store: Store
) -> None:
    live = await attempt()
    live.ctx.ask_policy = "http"
    async with serving(app) as connect, connect(live.token) as client:
        result = await client.call_tool(
            "ask_operator", {"prompt": "  which branch?  ", "options": ["main", "dev"]}
        )
    opened = body(result)
    assert not result.is_error
    assert opened["mode"] == "options"
    assert opened["answered"] is False
    async with store.reader() as reader:
        [view] = await reader.requests.list_views(live.run_id)
    assert view.id == opened["request_id"]
    assert view.prompt == "which branch?"
    assert view.source is RequestSource.agent
    assert view.options == [
        {"option_id": "main", "name": "main", "kind": None},
        {"option_id": "dev", "name": "dev", "kind": None},
    ]


async def test_wait_answer_reports_the_answer_the_operator_gave(
    app: FastAPI, client: httpx.AsyncClient, attempt: Claim
) -> None:
    """The operator answers over the API; the agent reads it as a tool."""

    live = await attempt()
    live.ctx.ask_policy = "http"
    async with serving(app) as connect, connect(live.token) as mcp_client:
        opened = body(await mcp_client.call_tool("ask_operator", {"prompt": "ship?"}))
        pending = body(
            await mcp_client.call_tool(
                "wait_answer", {"request_id": opened["request_id"]}
            )
        )
        assert pending == {"request_id": opened["request_id"], "answered": False}
        answered = await client.post(
            f"/api/requests/{opened['request_id']}/answer", json={"value": "yes"}
        )
        assert answered.status_code == 200, answered.text
        result = await mcp_client.call_tool(
            "wait_answer", {"request_id": opened["request_id"]}
        )
    assert body(result) == {
        "request_id": opened["request_id"],
        "answered": True,
        "answer": "yes",
        "answered_by": "user",
    }


async def test_ask_operator_can_wait_for_the_answer_in_one_call(
    app: FastAPI, client: httpx.AsyncClient, attempt: Claim, store: Store
) -> None:
    """A tool call is already a turn the model waits inside (08 §MCP)."""

    live = await attempt()
    live.ctx.ask_policy = "http"

    async def answer_when_it_appears() -> None:
        for _ in range(400):
            async with store.reader() as reader:
                views = await reader.requests.list_views(live.run_id)
            if views:
                await client.post(
                    f"/api/requests/{views[0].id}/answer", json={"value": "dev"}
                )
                return
            await asyncio.sleep(0.01)
        raise AssertionError("the request was never opened")

    async with serving(app) as connect, connect(live.token) as mcp_client:
        answering = asyncio.create_task(answer_when_it_appears())
        try:
            result = await mcp_client.call_tool(
                "ask_operator", {"prompt": "which branch?", "wait": 10}
            )
        finally:
            await answering
    answered = body(result)
    assert answered["answered"] is True
    assert answered["answer"] == "dev"


async def test_a_request_of_another_task_is_not_readable(
    app: FastAPI, attempt: Claim
) -> None:
    """A token names one attempt, and reads only what it opened."""

    mine = await attempt()
    theirs = await attempt()
    theirs.ctx.ask_policy = "http"
    mine.ctx.ask_policy = "http"
    async with serving(app) as connect:
        async with connect(theirs.token) as client:
            opened = body(await client.call_tool("ask_operator", {"prompt": "ship?"}))
        async with connect(mine.token) as client:
            result = await client.call_tool(
                "wait_answer", {"request_id": opened["request_id"]}
            )
    assert result.is_error
    assert body(result)["code"] == "not_found"


# --------------------------------------------------------------------------
# The credential
# --------------------------------------------------------------------------


async def test_a_wrong_token_never_reaches_the_server(
    app: FastAPI, attempt: Claim
) -> None:
    """The guard answers before a byte of MCP is parsed."""

    await attempt()
    with pytest.raises(BaseExceptionGroup) as caught:
        async with serving(app) as connect, connect("not-the-token") as client:
            await client.list_tools()
    # The transport reports the refusal as the error the session failed
    # with; what matters is that no tool was ever listed to be called.
    assert caught.value.subgroup(MCPError) is not None


async def test_a_wrong_token_is_the_apis_own_403(
    app: FastAPI, client: httpx.AsyncClient, attempt: Claim
) -> None:
    """08 §Conventions' error body, at the HTTP layer where MCP is not yet."""

    live = await attempt()
    initialize = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "probe", "version": "0"},
        },
    }
    accept = {"Accept": "application/json, text/event-stream"}
    async with app.router.lifespan_context(app):
        for headers in ({}, {mcp.TOKEN_HEADER: "not-the-token"}):
            response = await client.post(
                mcp.MCP_PATH, json=initialize, headers={**accept, **headers}
            )
            assert response.status_code == 403, response.text
            assert response.json()["code"] == "forbidden"
        # And the right one is not refused.
        accepted = await client.post(
            mcp.MCP_PATH, json=initialize, headers={**accept, **live.headers}
        )
    assert accepted.status_code == 200, accepted.text


async def test_a_token_dies_with_the_attempt_it_was_minted_for(
    app: FastAPI, client: httpx.AsyncClient, attempt: Claim, store: Store
) -> None:
    """12 §Task tokens: valid only while `in_progress` or `waiting`."""

    live = await attempt()
    async with store.uow() as uow:
        await uow.tasks.finish(live.task_id, "done", result=None)
    response = await client.post(
        mcp.MCP_PATH,
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        headers=live.headers,
    )
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


# --------------------------------------------------------------------------
# The document
# --------------------------------------------------------------------------


def test_openapi_lists_the_endpoint_under_agent_as_an_opaque_route(
    app: FastAPI,
) -> None:
    """08 §MCP: the snapshot records its existence and its auth scheme."""

    operation = app.openapi()["paths"][mcp.MCP_PATH]["post"]
    assert operation["tags"] == ["agent"]
    assert [one["name"] for one in operation["parameters"]] == [mcp.TOKEN_HEADER]
    # Opaque: a body, with nothing said about its shape.
    assert operation["requestBody"]["content"]["application/json"]["schema"] == {}
    assert "403" in operation["responses"]

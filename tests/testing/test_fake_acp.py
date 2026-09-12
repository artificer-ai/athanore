"""`FakeACPAgent` against a raw ACP client: every key of 13 §Fakes.

The fake is the only agent CI runs, so this suite is what makes every
downstream agent, API and E2E test mean something. It drives the
subprocess with a hand-rolled JSON-RPC client rather than through
``ACPAgent`` — which does not exist until T039 — for two reasons: the
fake's contract is the *wire*, and a fake asserted against the façade
that consumes it could agree with it about something the protocol does
not say.

One test per scenario key, plus the handshake, the sessions that survive
the process (23 §The fake: a second ``RawACPClient`` is the second
process), and the two failure modes that matter: an unknown key, and a
scenario that names a shape the vocabulary does not have.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from athanore.testing import FAKE_ACP, ScenarioError, scenario, scenario_file
from athanore.testing.fake_acp import ENV_MARKER, REJECT_FIRST

TOKEN = "task-token-abc"


# --------------------------------------------------------------------------
# A raw ACP client: enough JSON-RPC to talk to an agent, and no opinions.
# --------------------------------------------------------------------------


class RawACPClient:
    """Newline-delimited JSON-RPC over a child's stdio, both directions.

    Answers the two requests an agent initiates — a permission and an
    elicitation — from handlers a test may replace, records everything
    that arrives, and hands back results.
    """

    def __init__(
        self,
        command: list[str],
        *,
        env: dict[str, str] | None = None,
        permission: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        elicitation: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> None:
        self.command = command
        self.env = {**os.environ, **(env or {})}
        self.updates: list[dict[str, Any]] = []
        self.permissions: list[dict[str, Any]] = []
        self.elicitations: list[dict[str, Any]] = []
        self.session_id = ""
        self._permission = permission or _allow_once
        self._elicitation = elicitation or _accept_form
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._next_id = 1

    async def __aenter__(self) -> RawACPClient:
        self.process = await asyncio.create_subprocess_exec(
            *self.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self.env,
        )
        self._reader = asyncio.get_running_loop().create_task(self._read_loop())
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self.process.stdin is not None:
            self.process.stdin.close()
        try:
            await asyncio.wait_for(self.process.wait(), timeout=5)
        except TimeoutError:  # pragma: no cover - a wedged fake
            self.process.kill()
            await self.process.wait()
        self._reader.cancel()
        assert self.process.stderr is not None
        self.stderr = (await self.process.stderr.read()).decode()

    # -- framing ---------------------------------------------------------

    def _send(self, message: dict[str, Any]) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write((json.dumps(message) + "\n").encode())

    async def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """One request; the ``result``, or the ``error`` as an exception."""

        message = await self.send(method, params)
        if "error" in message:
            raise ACPError(message["error"])
        return message["result"]

    async def send(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """One request; the whole response, error and all."""

        request_id = self._next_id
        self._next_id += 1
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[request_id] = future
        self._send(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        )
        return await asyncio.wait_for(future, timeout=30)

    async def _read_loop(self) -> None:
        assert self.process.stdout is not None
        while True:
            line = await self.process.stdout.readline()
            if not line:
                return
            text = line.decode().strip()
            if not text:
                continue
            message = json.loads(text)
            if message.get("method") and message.get("id") is not None:
                self._answer(message)
            elif message.get("method"):
                self.updates.append(message)
            else:
                future = self._pending.pop(message["id"], None)
                if future is not None and not future.done():
                    future.set_result(message)

    def _answer(self, message: dict[str, Any]) -> None:
        params = message.get("params") or {}
        if message["method"] == "session/request_permission":
            self.permissions.append(params)
            result = self._permission(params)
        elif message["method"] == "elicitation/create":
            self.elicitations.append(params)
            result = self._elicitation(params)
        else:  # pragma: no cover - the fake initiates nothing else
            raise AssertionError(f"unexpected agent request {message['method']}")
        self._send({"jsonrpc": "2.0", "id": message["id"], "result": result})

    # -- the methods a session needs ---------------------------------------

    async def initialize(self) -> dict[str, Any]:
        return await self.call(
            "initialize", {"protocolVersion": 1, "clientCapabilities": {}}
        )

    async def handshake(self, **new_session: Any) -> dict[str, Any]:
        """``initialize`` then ``session/new``; returns both results."""

        initialize = await self.initialize()
        params = {"cwd": os.getcwd(), "mcpServers": [], **new_session}
        session = await self.call("session/new", params)
        self.session_id = session["sessionId"]
        return {"initialize": initialize, "session": session}

    async def load(self, session_id: str, **params: Any) -> dict[str, Any]:
        """``session/load``: a second process opening without ``session/new``."""

        return await self._reopen("session/load", session_id, params)

    async def resume(self, session_id: str, **params: Any) -> dict[str, Any]:
        return await self._reopen("session/resume", session_id, params)

    async def _reopen(
        self, method: str, session_id: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        result = await self.call(
            method,
            {"sessionId": session_id, "cwd": os.getcwd(), "mcpServers": [], **params},
        )
        self.session_id = session_id
        return result

    async def prompt(self, text: str = "do the work") -> dict[str, Any]:
        return await self.call(
            "session/prompt",
            {
                "sessionId": self.session_id,
                "prompt": [{"type": "text", "text": text}],
            },
        )

    # -- what arrived ------------------------------------------------------

    def chunks(self, kind: str) -> list[dict[str, Any]]:
        return [
            update["params"]["update"]
            for update in self.updates
            if update["params"]["update"].get("sessionUpdate") == kind
        ]

    def texts(self, kind: str = "agent_message_chunk") -> list[str]:
        return [chunk["content"]["text"] for chunk in self.chunks(kind)]


class ACPError(Exception):
    """A JSON-RPC error the agent answered with."""

    def __init__(self, error: dict[str, Any]) -> None:
        super().__init__(error.get("message", ""))
        self.error = error


def _allow_once(params: dict[str, Any]) -> dict[str, Any]:
    """Select by kind, never by index (20 §Finding 1)."""

    chosen = next(
        option for option in params["options"] if option["kind"] == "allow_once"
    )
    return {"outcome": {"outcome": "selected", "optionId": chosen["optionId"]}}


def _accept_form(params: dict[str, Any]) -> dict[str, Any]:
    return {"action": "accept", "content": {"name": "operator", "count": 2}}


# --------------------------------------------------------------------------
# The task API the fake POSTs to, and an MCP server for the `mcp` tier.
# --------------------------------------------------------------------------


class TaskAPI:
    """The two agent endpoints of 08 the fake uses, and what reached them."""

    def __init__(self, base: str) -> None:
        self.base = base
        self.logs: list[str] = []
        self.submissions: list[Any] = []
        self.tokens: list[str] = []


async def _serve(
    app: Any, **config: Any
) -> tuple[uvicorn.Server, asyncio.Task[None], int]:
    """Serve ``app`` on a free loopback port; the fake reaches it by URL."""

    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", **config)
    )
    task = asyncio.get_running_loop().create_task(server.serve())
    # uvicorn signals readiness with a flag and no event, so this is a poll.
    while not server.started:  # noqa: ASYNC110
        await asyncio.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    return server, task, port


async def _stop(server: uvicorn.Server, task: asyncio.Task[None]) -> None:
    server.should_exit = True
    await asyncio.wait_for(task, timeout=10)


@pytest.fixture
async def task_api() -> AsyncIterator[TaskAPI]:
    """A stand-in for 08 §Agent: `/log` always takes, `/submit` validates.

    The endpoint itself is T045's. What this has to be faithful about is
    the two things the fake depends on — the paths, and the
    ``X-Athanore-Token`` header — plus the 422 that drives the repair
    path, which here is "a submission must carry ``ok``".
    """

    app = FastAPI()
    state = TaskAPI("")

    @app.post("/api/agent/tasks/{task_id}/log")
    async def append_log(task_id: int, request: Request) -> JSONResponse:
        state.tokens.append(request.headers.get("X-Athanore-Token", ""))
        state.logs.append((await request.json())["text"])
        return JSONResponse({"id": len(state.logs)})

    @app.post("/api/agent/tasks/{task_id}/submit")
    async def submit(task_id: int, request: Request) -> JSONResponse:
        state.tokens.append(request.headers.get("X-Athanore-Token", ""))
        payload = await request.json()
        if not isinstance(payload, dict) or "ok" not in payload:
            return JSONResponse(
                {"error": "invalid", "errors": [{"loc": ["ok"], "type": "missing"}]},
                status_code=422,
            )
        state.submissions.append(payload)
        return JSONResponse({"id": len(state.submissions)})

    server, task, port = await _serve(app)
    state.base = f"http://127.0.0.1:{port}/api/agent/tasks/7"
    try:
        yield state
    finally:
        await _stop(server, task)


@pytest.fixture
def task_env(task_api: TaskAPI) -> dict[str, str]:
    """19 §Environment: what the façade exports to the subprocess."""

    return {"ATHANORE_TASK_URL": task_api.base, "ATHANORE_TASK_TOKEN": TOKEN}


@pytest.fixture
async def mcp_server() -> AsyncIterator[dict[str, Any]]:
    """A real MCP server over streamable HTTP, with one tool and one header.

    Stands in for the athanore tool server of T045a: what `mcp_calls`
    has to prove is that the fake connects to the server it was handed on
    ``session/new``, sends the header that came with it, and reports the
    results back as tool calls.
    """

    from mcp.server.mcpserver import MCPServer

    seen: list[str] = []
    mcp = MCPServer(name="athanore-test")

    @mcp.tool()
    def append_log(text: str) -> str:
        """Append one line to the work log."""
        return f"logged: {text}"

    app = mcp.streamable_http_app()

    async def capture(scope: Any, receive: Any, send: Any) -> None:
        """One ASGI wrapper, so the lifespan still reaches the server."""

        if scope["type"] == "http":
            headers = {key.decode(): value.decode() for key, value in scope["headers"]}
            seen.append(headers.get("x-athanore-token", ""))
        await app(scope, receive, send)

    server, task, port = await _serve(capture, lifespan="on")
    try:
        yield {
            "type": "http",
            "name": "athanore",
            "url": f"http://127.0.0.1:{port}/mcp",
            "headers": [{"name": "X-Athanore-Token", "value": TOKEN}],
            "tokens": seen,
        }
    finally:
        await _stop(server, task)


@pytest.fixture
def logs(tmp_path: Path) -> Iterator[tuple[Path, Path]]:
    yield tmp_path / "requests.jsonl", tmp_path / "responses.jsonl"


def read_lines(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def read_session(directory: Path, session_id: str) -> list[dict[str, Any]]:
    """The fake's session file: ``<dir>/<sessionId>.json`` (23 §The fake)."""

    return json.loads((directory / f"{session_id}.json").read_text())


def sent(client: RawACPClient) -> list[dict[str, Any]]:
    """The update objects the client received, in arrival order."""

    return [update["params"]["update"] for update in client.updates]


def user_chunk(text: str) -> dict[str, Any]:
    return {
        "sessionUpdate": "user_message_chunk",
        "content": {"type": "text", "text": text},
    }


# --------------------------------------------------------------------------
# The handshake.
# --------------------------------------------------------------------------


async def test_the_fake_speaks_initialize_new_session_and_prompt() -> None:
    async with RawACPClient(scenario()) as client:
        handshake = await client.handshake()
        response = await client.prompt()
    assert handshake["initialize"]["protocolVersion"] == 1
    assert handshake["session"]["sessionId"]
    assert response == {"stopReason": "end_turn"}


async def test_an_unknown_method_is_a_json_rpc_error() -> None:
    async with RawACPClient(scenario()) as client:
        await client.handshake()
        message = await client.send("session/fork", {"sessionId": client.session_id})
    assert message["error"]["code"] == -32601


# --------------------------------------------------------------------------
# One test per key of 13 §Fakes.
# --------------------------------------------------------------------------


async def test_text_is_one_agent_message_chunk_per_string() -> None:
    async with RawACPClient(scenario(text=["one ", "two"])) as client:
        await client.handshake()
        await client.prompt()
    assert client.texts() == ["one ", "two"]


async def test_thoughts_are_agent_thought_chunks() -> None:
    async with RawACPClient(scenario(thoughts=["hmm"], text=["done"])) as client:
        await client.handshake()
        await client.prompt()
    assert client.texts("agent_thought_chunk") == ["hmm"]
    assert client.texts() == ["done"]


async def test_a_tool_call_count_emits_a_start_and_a_completion_each() -> None:
    async with RawACPClient(scenario(tool_calls=3)) as client:
        await client.handshake()
        await client.prompt()
    starts = client.chunks("tool_call")
    assert len(starts) == 3
    assert [call["toolCallId"] for call in starts] == ["call_0", "call_1", "call_2"]
    updates = client.chunks("tool_call_update")
    assert [update["status"] for update in updates] == ["completed"] * 3


async def test_tool_calls_may_be_described_one_by_one() -> None:
    calls = [{"title": "run the gate", "kind": "execute", "raw_input": {"cmd": "make"}}]
    async with RawACPClient(scenario(tool_calls=calls)) as client:
        await client.handshake()
        await client.prompt()
    start = client.chunks("tool_call")[0]
    assert start["title"] == "run the gate"
    assert start["kind"] == "execute"
    assert start["rawInput"] == {"cmd": "make"}


async def test_reject_first_is_the_claude_option_order() -> None:
    """The shorthand exists so a selection-by-index bug denies (20 §1)."""

    async with RawACPClient(scenario(permissions=["reject_first"])) as client:
        await client.handshake()
        await client.prompt()
    assert client.permissions[0]["options"] == REJECT_FIRST
    assert client.permissions[0]["toolCall"]["toolCallId"] == "perm_0"


async def test_permissions_are_sent_in_order_with_the_options_listed() -> None:
    requests = [
        {"title": "first", "options": [{"kind": "allow_once", "name": "Yes"}]},
        {
            "title": "second",
            "options": [
                {"kind": "reject_once", "option_id": "no"},
                {"kind": "allow_once"},
            ],
        },
    ]
    async with RawACPClient(scenario(permissions=requests)) as client:
        await client.handshake()
        await client.prompt()
    assert [p["toolCall"]["title"] for p in client.permissions] == ["first", "second"]
    assert client.permissions[0]["options"] == [
        {"optionId": "allow_once", "name": "Yes", "kind": "allow_once"}
    ]
    assert [option["optionId"] for option in client.permissions[1]["options"]] == [
        "no",
        "allow_once",
    ]


async def test_a_form_elicitation_carries_the_scripted_schema() -> None:
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }
    command = scenario(elicitations=[{"schema": schema, "mode": "form"}])
    async with RawACPClient(command) as client:
        await client.handshake()
        await client.prompt()
    assert client.elicitations[0]["mode"] == "form"
    assert client.elicitations[0]["requestedSchema"] == schema


async def test_a_url_elicitation_carries_a_url_and_no_schema() -> None:
    """URL mode is the one the `ask` policy declines (05 §Elicitation)."""

    declined = {"action": "decline"}
    command = scenario(elicitations=[{"mode": "url"}])
    async with RawACPClient(command, elicitation=lambda params: declined) as client:
        await client.handshake()
        await client.prompt()
    assert client.elicitations[0]["mode"] == "url"
    assert client.elicitations[0]["url"].startswith("https://")
    assert "requestedSchema" not in client.elicitations[0]


async def test_session_new_advertises_pis_two_config_options_by_default() -> None:
    async with RawACPClient(scenario()) as client:
        handshake = await client.handshake()
    options = handshake["session"]["configOptions"]
    assert [option["category"] for option in options] == ["model", "thought_level"]
    assert options[0]["currentValue"] == options[0]["options"][0]["value"]


async def test_config_options_are_advertised_and_settable() -> None:
    options = [{"id": "llm", "category": "model", "values": ["a", "b"]}]
    async with RawACPClient(scenario(config_options=options)) as client:
        handshake = await client.handshake()
        result = await client.call(
            "session/set_config_option",
            {"sessionId": client.session_id, "configId": "llm", "value": "b"},
        )
    advertised = handshake["session"]["configOptions"][0]
    assert advertised["id"] == "llm"
    assert advertised["category"] == "model"
    assert [choice["value"] for choice in advertised["options"]] == ["a", "b"]
    assert result["configOptions"][0]["currentValue"] == "b"


async def test_reject_config_makes_setting_that_id_fail() -> None:
    options = [{"id": "llm", "category": "model", "values": ["a"]}]
    command = scenario(config_options=options, reject_config=["llm"])
    async with RawACPClient(command) as client:
        await client.handshake()
        message = await client.send(
            "session/set_config_option",
            {"sessionId": client.session_id, "configId": "llm", "value": "a"},
        )
    assert message["error"]["code"] == -32602
    assert "llm" in message["error"]["message"]


async def test_usage_rides_on_the_prompt_response() -> None:
    usage = {"input": 1000, "output": 500, "thought": 40, "cache_read": 7}
    async with RawACPClient(scenario(usage=usage)) as client:
        await client.handshake()
        response = await client.prompt()
    assert response["usage"] == {
        "inputTokens": 1000,
        "outputTokens": 500,
        "totalTokens": 1500,
        "thoughtTokens": 40,
        "cachedReadTokens": 7,
    }


@pytest.mark.parametrize("reason", ["end_turn", "refusal", "cancelled"])
async def test_stop_reason_is_what_the_turn_ends_with(reason: str) -> None:
    async with RawACPClient(scenario(stop_reason=reason)) as client:
        await client.handshake()
        response = await client.prompt()
    assert response["stopReason"] == reason


async def test_sleep_s_delays_the_answer_to_the_prompt() -> None:
    """The timeout path of 05 needs a turn that does not come back."""

    async with RawACPClient(scenario(sleep_s=0.4)) as client:
        await client.handshake()
        started = time.monotonic()
        await client.prompt()
        elapsed = time.monotonic() - started
    assert elapsed >= 0.35


async def test_a_session_file_is_written_in_pis_layout_before_any_prompt(
    tmp_path: Path,
) -> None:
    spec = {
        "dir": str(tmp_path / "sessions"),
        "cost": 0.25,
        "stop_reason": "length",
        "model": "openrouter/qwen3",
    }
    async with RawACPClient(scenario(session_file=spec, text=["hi"])) as client:
        handshake = await client.handshake()
        session_id = handshake["session"]["sessionId"]
    written = list((tmp_path / "sessions").glob(f"**/*_{session_id}.jsonl"))
    assert len(written) == 1
    lines = [json.loads(line) for line in written[0].read_text().splitlines()]
    assert lines[0] == {
        "type": "session",
        "version": 3,
        "id": session_id,
        "timestamp": lines[0]["timestamp"],
        "cwd": "/fake-cwd",
    }
    assert lines[1]["provider"] == "openrouter"
    assert lines[2]["message"]["stopReason"] == "length"
    assert lines[2]["message"]["usage"]["cost"]["total"] == 0.25
    assert lines[2]["message"]["content"][0]["text"] == "hi"


async def test_a_session_file_without_a_cost_carries_no_cost_key(
    tmp_path: Path,
) -> None:
    """Unknown is omitted: a zero here would be a number nobody measured."""

    spec = {"dir": str(tmp_path / "sessions")}
    async with RawACPClient(scenario(session_file=spec)) as client:
        await client.handshake()
    written = list((tmp_path / "sessions").glob("**/*.jsonl"))
    message = json.loads(written[0].read_text().splitlines()[2])
    assert "cost" not in message["message"]["usage"]
    assert message["message"]["stopReason"] == "endTurn"


async def test_log_posts_the_deliverable_to_the_task_api(
    task_api: TaskAPI, task_env: dict[str, str], logs: tuple[Path, Path]
) -> None:
    _requests, responses = logs
    command = scenario(log="the deliverable", response_log=str(responses))
    async with RawACPClient(command, env=task_env) as client:
        await client.handshake()
        await client.prompt()
    assert task_api.logs == ["the deliverable"]
    assert task_api.tokens == [TOKEN]
    assert read_lines(responses) == [{"log": 200}]


async def test_submit_posts_each_payload_and_the_last_valid_one_wins(
    task_api: TaskAPI, task_env: dict[str, str], logs: tuple[Path, Path]
) -> None:
    _requests, responses = logs
    command = scenario(
        submit=[{"wrong": 1}, {"ok": True, "n": 2}], response_log=str(responses)
    )
    async with RawACPClient(command, env=task_env) as client:
        await client.handshake()
        await client.prompt()
    assert read_lines(responses) == [{"submit": 422}, {"submit": 200}]
    assert task_api.submissions == [{"ok": True, "n": 2}]


async def test_a_lone_invalid_submission_leaves_the_422_for_a_repair_turn(
    task_api: TaskAPI, task_env: dict[str, str], logs: tuple[Path, Path]
) -> None:
    """13's reason the list form exists: the 422 + repair path (05 §5)."""

    _requests, responses = logs
    command = scenario(
        submit={"wrong": 1},
        repair_submit={"ok": True, "fixed": True},
        response_log=str(responses),
    )
    async with RawACPClient(command, env=task_env) as client:
        await client.handshake()
        await client.prompt()
        await client.prompt("Your turn ended, but no valid structured result…")
    assert read_lines(responses) == [{"submit": 422}, {"submit": 200}]
    assert task_api.submissions == [{"ok": True, "fixed": True}]


async def test_a_submission_with_nowhere_to_go_is_reported_not_swallowed(
    logs: tuple[Path, Path],
) -> None:
    """No task URL in the environment is a misconfiguration, and says so."""

    _requests, responses = logs
    command = scenario(submit={"ok": True}, response_log=str(responses))
    async with RawACPClient(
        command, env={"ATHANORE_TASK_URL": "", "ATHANORE_TASK_TOKEN": ""}
    ) as client:
        await client.handshake()
        await client.prompt()
    assert read_lines(responses) == [
        {"submit": None, "error": "ATHANORE_TASK_URL/TOKEN are not set"}
    ]
    assert "ATHANORE_TASK_URL/TOKEN are not set" in client.stderr


async def test_the_request_log_records_every_received_request(
    logs: tuple[Path, Path],
) -> None:
    requests, _responses = logs
    options = [{"id": "llm", "category": "model", "values": ["a", "b"]}]
    command = scenario(config_options=options, request_log=str(requests))
    async with RawACPClient(command) as client:
        await client.handshake()
        await client.call(
            "session/set_config_option",
            {"sessionId": client.session_id, "configId": "llm", "value": "b"},
        )
    received = read_lines(requests)
    assert [entry["method"] for entry in received] == [
        "initialize",
        "session/new",
        "session/set_config_option",
    ]
    assert received[2]["params"]["configId"] == "llm"


async def test_the_response_log_records_what_the_client_answered(
    logs: tuple[Path, Path],
) -> None:
    _requests, responses = logs
    command = scenario(permissions=["reject_first"], response_log=str(responses))
    async with RawACPClient(command) as client:
        await client.handshake()
        await client.prompt()
    answered = read_lines(responses)
    assert answered[0]["result"]["outcome"]["optionId"] == "allow"


async def test_env_echo_lists_the_environment_the_child_was_given() -> None:
    """The scrub assertions of 05 §Session lifecycle need to see the env."""

    async with RawACPClient(
        scenario(env_echo=True), env={"ATHANORE_MARKER": "kept"}
    ) as client:
        await client.handshake()
        await client.prompt()
    listing = client.texts()[0]
    assert listing.startswith(f"{ENV_MARKER}\n")
    assert "ATHANORE_MARKER=kept" in listing


async def test_advertise_mcp_reports_the_capability_and_records_the_server(
    logs: tuple[Path, Path],
) -> None:
    requests, _responses = logs
    servers = [
        {
            "type": "http",
            "name": "athanore",
            "url": "http://127.0.0.1:1/mcp/agent",
            "headers": [{"name": "X-Athanore-Token", "value": TOKEN}],
        }
    ]
    command = scenario(advertise_mcp=True, request_log=str(requests))
    async with RawACPClient(command) as client:
        handshake = await client.handshake(mcpServers=servers)
    capabilities = handshake["initialize"]["agentCapabilities"]["mcpCapabilities"]
    assert capabilities == {"http": True, "sse": False}
    recorded = read_lines(requests)[1]["params"]["mcpServers"]
    assert recorded == servers


async def test_no_advertisement_means_no_mcp_capability() -> None:
    async with RawACPClient(scenario()) as client:
        handshake = await client.handshake()
    capabilities = handshake["initialize"]["agentCapabilities"]["mcpCapabilities"]
    assert capabilities == {"http": False, "sse": False}


async def test_mcp_calls_reach_the_server_session_new_carried(
    mcp_server: dict[str, Any],
) -> None:
    """The `mcp` tier end to end: connect, call, report as a tool result."""

    server = {key: mcp_server[key] for key in ("type", "name", "url", "headers")}
    command = scenario(
        advertise_mcp=True,
        mcp_calls=[{"tool": "append_log", "args": {"text": "from the agent"}}],
    )
    async with RawACPClient(command) as client:
        await client.handshake(mcpServers=[server])
        await client.prompt()
    start = client.chunks("tool_call")[0]
    assert start["title"] == "append_log"
    assert start["rawInput"] == {"text": "from the agent"}
    update = client.chunks("tool_call_update")[0]
    assert update["content"][0]["content"]["text"] == "logged: from the agent"
    assert TOKEN in mcp_server["tokens"]


async def test_mcp_calls_without_a_server_fail_the_turn_loudly() -> None:
    command = scenario(mcp_calls=[{"tool": "append_log", "args": {}}])
    async with RawACPClient(command) as client:
        await client.handshake()
        message = await client.send(
            "session/prompt",
            {"sessionId": client.session_id, "prompt": [{"type": "text", "text": "x"}]},
        )
    assert message["error"]["code"] == -32603
    assert "no HTTP MCP server" in message["error"]["message"]


# --------------------------------------------------------------------------
# Sessions across processes (23 §The fake, D257).
# --------------------------------------------------------------------------


async def test_sessions_advertises_load_session_and_resume_on_request(
    tmp_path: Path,
) -> None:
    sessions = {"dir": str(tmp_path / "sessions")}
    async with RawACPClient(scenario(sessions=sessions)) as client:
        capabilities = (await client.initialize())["agentCapabilities"]
    assert capabilities["loadSession"] is True
    assert "sessionCapabilities" not in capabilities

    async with RawACPClient(scenario(sessions={**sessions, "resume": True})) as client:
        capabilities = (await client.initialize())["agentCapabilities"]
    assert capabilities["loadSession"] is True
    assert capabilities["sessionCapabilities"] == {"resume": {}}

    async with RawACPClient(scenario()) as client:
        capabilities = (await client.initialize())["agentCapabilities"]
    assert capabilities["loadSession"] is False
    assert "sessionCapabilities" not in capabilities


async def test_session_new_creates_the_file_and_a_turn_fills_it_in_order(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "sessions"
    command = scenario(
        sessions={"dir": str(directory)},
        thoughts=["hmm"],
        text=["one", "two"],
        tool_calls=1,
    )
    async with RawACPClient(command) as client:
        await client.handshake()
        assert read_session(directory, client.session_id) == []
        await client.prompt("first ask")
        recorded = read_session(directory, client.session_id)
    assert recorded == [user_chunk("first ask"), *sent(client)]
    assert [entry["sessionUpdate"] for entry in recorded] == [
        "user_message_chunk",
        "agent_thought_chunk",
        "agent_message_chunk",
        "agent_message_chunk",
        "tool_call",
        "tool_call_update",
    ]
    assert client.chunks("user_message_chunk") == []


async def test_a_second_process_loads_the_session_and_replays_the_file(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "sessions"
    command = scenario(sessions={"dir": str(directory)}, text=["one", "two"])
    async with RawACPClient(command) as first:
        await first.handshake()
        await first.prompt("first ask")
        session_id = first.session_id
    before = read_session(directory, session_id)
    assert before == [user_chunk("first ask"), *sent(first)]

    async with RawACPClient(command) as second:
        await second.initialize()
        result = await second.load(session_id)
        replayed = list(second.updates)
        await second.prompt("second ask")
        live = second.updates[len(replayed) :]
    assert [update["params"]["update"] for update in replayed] == before
    assert {update["params"]["sessionId"] for update in replayed} == {session_id}
    assert [o["category"] for o in result["configOptions"]] == [
        "model",
        "thought_level",
    ]
    assert "sessionId" not in result
    # The first-turn script ran again (D122), and the file grew by it.
    after = read_session(directory, session_id)
    assert after == [
        *before,
        user_chunk("second ask"),
        *[update["params"]["update"] for update in live],
    ]
    assert [update["params"]["update"]["content"]["text"] for update in live] == [
        "one",
        "two",
    ]


async def test_session_resume_answers_without_replaying(tmp_path: Path) -> None:
    directory = tmp_path / "sessions"
    command = scenario(sessions={"dir": str(directory), "resume": True}, text=["hi"])
    async with RawACPClient(command) as first:
        await first.handshake()
        await first.prompt("first ask")
        session_id = first.session_id
    before = read_session(directory, session_id)

    async with RawACPClient(command) as second:
        await second.initialize()
        result = await second.resume(session_id)
        assert second.updates == []
        await second.prompt("second ask")
    assert [o["id"] for o in result["configOptions"]] == ["model", "thought_level"]
    assert second.texts() == ["hi"]
    assert read_session(directory, session_id) == [
        *before,
        user_chunk("second ask"),
        *sent(second),
    ]


async def test_loading_an_unknown_session_is_invalid_params(tmp_path: Path) -> None:
    command = scenario(sessions={"dir": str(tmp_path / "sessions"), "resume": True})
    async with RawACPClient(command) as client:
        await client.initialize()
        load = await client.send(
            "session/load",
            {"sessionId": "nope", "cwd": os.getcwd(), "mcpServers": []},
        )
        resume = await client.send(
            "session/resume",
            {"sessionId": "nope", "cwd": os.getcwd(), "mcpServers": []},
        )
    assert load["error"] == {"code": -32602, "message": "no such session: nope"}
    assert resume["error"] == {"code": -32602, "message": "no such session: nope"}


async def test_resume_unadvertised_and_load_without_the_key_are_method_not_found(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "sessions"
    params = {"cwd": os.getcwd(), "mcpServers": []}
    async with RawACPClient(scenario(sessions={"dir": str(directory)})) as client:
        await client.handshake()
        message = await client.send(
            "session/resume", {"sessionId": client.session_id, **params}
        )
    assert message["error"]["code"] == -32601
    assert message["error"]["message"] == "method not found: session/resume"
    assert read_session(directory, client.session_id) == []

    async with RawACPClient(scenario()) as client:
        await client.handshake()
        load = await client.send(
            "session/load", {"sessionId": client.session_id, **params}
        )
        resume = await client.send(
            "session/resume", {"sessionId": client.session_id, **params}
        )
    assert load["error"]["code"] == -32601
    assert resume["error"]["code"] == -32601
    assert not (directory / f"{client.session_id}.json").exists()


async def test_mcp_servers_on_load_are_what_mcp_calls_connects_to(
    mcp_server: dict[str, Any], tmp_path: Path, logs: tuple[Path, Path]
) -> None:
    """`session/load` records `mcpServers` as `session/new` does."""

    directory = tmp_path / "sessions"
    requests, _responses = logs
    server = {key: mcp_server[key] for key in ("type", "name", "url", "headers")}
    command = scenario(
        sessions={"dir": str(directory)},
        advertise_mcp=True,
        mcp_calls=[{"tool": "append_log", "args": {"text": "later"}}],
        request_log=str(requests),
    )
    async with RawACPClient(command) as first:
        await first.handshake()
        session_id = first.session_id

    async with RawACPClient(command) as second:
        await second.initialize()
        await second.load(session_id, mcpServers=[server])
        await second.prompt()
    update = second.chunks("tool_call_update")[0]
    assert update["content"][0]["content"]["text"] == "logged: later"
    assert TOKEN in mcp_server["tokens"]
    received = read_lines(requests)
    assert [entry["method"] for entry in received] == [
        "initialize",
        "session/new",
        "initialize",
        "session/load",
        "session/prompt",
    ]
    assert received[3]["params"]["sessionId"] == session_id
    assert received[3]["params"]["mcpServers"] == [server]
    assert read_session(directory, session_id) == [
        user_chunk("do the work"),
        *sent(second),
    ]


# --------------------------------------------------------------------------
# Per-node selection, and the errors.
# --------------------------------------------------------------------------


async def test_scenarios_are_picked_per_node_from_the_kickoff_prompt(
    tmp_path: Path,
) -> None:
    """`<workflow>.<node>.json`, then `<node>.json`, then `default.json`."""

    directory = tmp_path / "scenarios"
    directory.mkdir()
    for name, text in (
        ("wf.review.json", "the wf review"),
        ("review.json", "any review"),
        ("qa.json", "any qa"),
        ("default.json", "the default"),
    ):
        (directory / name).write_text(json.dumps({"text": [text]}))

    async def say(node: str, workflow: str) -> list[str]:
        env = {"ATHANORE_FAKE_SCENARIOS": str(directory)}
        async with RawACPClient(FAKE_ACP, env=env) as client:
            await client.handshake()
            await client.prompt(
                f'Work on task 1 — stage "{node}" of workflow "{workflow}" (run R).'
            )
            return client.texts()

    assert await say("review", "wf") == ["the wf review"]
    assert await say("review", "other") == ["any review"]
    assert await say("qa", "wf") == ["any qa"]
    assert await say("build", "wf") == ["the default"]


async def test_the_default_scenario_answers_the_handshake(tmp_path: Path) -> None:
    """`initialize` and `session/new` land before any node is named."""

    directory = tmp_path / "scenarios"
    directory.mkdir()
    (directory / "default.json").write_text(json.dumps({"advertise_mcp": True}))
    env = {"ATHANORE_FAKE_SCENARIOS": str(directory)}
    async with RawACPClient(FAKE_ACP, env=env) as client:
        handshake = await client.handshake()
    capabilities = handshake["initialize"]["agentCapabilities"]["mcpCapabilities"]
    assert capabilities["http"] is True


async def test_a_single_scenario_may_come_from_the_environment(
    tmp_path: Path,
) -> None:
    path = scenario_file(text=["from the env"])
    env = {"ATHANORE_FAKE_SCENARIO": str(path)}
    async with RawACPClient(FAKE_ACP, env=env) as client:
        await client.handshake()
        await client.prompt()
    assert client.texts() == ["from the env"]


def test_an_unknown_scenario_key_is_an_error_at_the_call_site() -> None:
    """A typo must fail loudly rather than silently testing nothing (13)."""

    with pytest.raises(ScenarioError) as caught:
        scenario(txet=["oops"])
    assert "txet" in str(caught.value)
    assert "text" in str(caught.value)


def test_a_misshapen_value_is_an_error_too() -> None:
    with pytest.raises(ScenarioError, match="usage"):
        scenario(usage={"input": 1})
    with pytest.raises(ScenarioError, match="permissions"):
        scenario(permissions=[{"options": [{"name": "Allow"}]}])
    with pytest.raises(ScenarioError, match="stop_reason"):
        scenario(stop_reason="finished")
    with pytest.raises(ScenarioError, match="sessions.dir"):
        scenario(sessions={"dir": 1})
    with pytest.raises(ScenarioError, match="sessions.resume"):
        scenario(sessions={"dir": "/tmp/x", "resume": "yes"})
    with pytest.raises(ScenarioError, match="sessions.*replay"):
        scenario(sessions={"dir": "/tmp/x", "replay": True})


async def test_an_unknown_key_in_a_scenario_file_kills_the_fake(
    tmp_path: Path,
) -> None:
    """The same check, on the far side: a hand-written file is checked too."""

    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"txet": ["oops"]}))
    process = await asyncio.create_subprocess_exec(
        *FAKE_ACP,
        "--scenario",
        str(path),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _out, err = await process.communicate()
    assert process.returncode == 2
    assert "txet" in err.decode()

"""The pi extension: five tools over the agent HTTP API (T040a).

05 §Tooling tiers gives pi the ``native`` tier because it has no MCP
client, and ``examples/pi/extensions/athanore.ts`` is what makes that
tier true. Three things are worth testing about it, and they need three
different harnesses:

- **it is a pi extension.** ``pi -e`` loads it, which is the only check
  that pi's own module loader and its startup path accept the file; a
  parse error there exits ``1`` before anything else runs, so the smoke
  is not vacuous. Skipped, not failed, where pi is not installed.
- **it registers the five tools of 08 §MCP, described in 19's words.**
  A pi extension is a factory that is handed an ``ExtensionAPI``, so the
  smallest honest harness is the smallest ``ExtensionAPI``:
  ``probe_extension.mjs`` records what was registered and hands it back
  as JSON.
- **each tool is that endpoint.** The same probe calls one tool against
  a server that records what arrived, which is where the substrate claim
  of 05 — "all three tiers sit on the agent HTTP API of 08" — is either
  true or not: the method, the path, and the token in the header and
  nowhere else (12 §Task tokens).

The fourth assertion is on the other side of the same tier: the prompt a
``native`` agent is handed carries the tools rather than curl lines, and
carries no token at all.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from collections.abc import Awaitable, Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from athanore.engine.context import TaskContext
from pi import ATHANORE_EXTENSION, PiAgent

#: The five tools of 08 §MCP, in the order 19's tier block names them.
TOOLS = ["get_task", "append_log", "submit_result", "ask_operator", "wait_answer"]

#: The task this fake API serves, as ``{base}`` of 19: the agent-facing
#: root of one task, which is what the façade exports as
#: ``ATHANORE_TASK_URL``.
TASK_PATH = "/api/agent/tasks/12"

TOKEN = "tok-extension-9c73"

#: The node's ``output_model`` schema, as `GET /api/agent/tasks/{id}`
#: reports it (08). ``submit_result``'s input schema *is* this.
OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "title": "Review",
    "properties": {
        "verdict": {"type": "string"},
        "notes": {"type": "string"},
    },
    "required": ["verdict"],
}

PROBE = Path(__file__).parent / "probe_extension.mjs"


class Recorded:
    """One request the extension made, as the server saw it."""

    def __init__(self, method: str, path: str, headers: dict[str, str], body: str):
        self.method = method
        self.path = path
        self.headers = headers
        self.body = body

    @property
    def json(self) -> Any:
        return json.loads(self.body) if self.body else None


class TaskAPI:
    """The half of 08 §Agent-facing that the extension actually calls.

    Not a mock of the extension's HTTP client — a server, so what is
    asserted is what went over the wire. The 422 is here because it is
    the one response the model has to see the body of: it carries the
    validation errors and the schema, and the repair happens in the same
    turn (05 §Submissions).
    """

    def __init__(self) -> None:
        self.requests: list[Recorded] = []
        self.server: ThreadingHTTPServer | None = None

    @property
    def base(self) -> str:
        assert self.server is not None
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}{TASK_PATH}"

    def handle(self, request: Recorded) -> tuple[int, dict[str, Any]]:
        self.requests.append(request)
        path = request.path.split("?")[0]
        if request.method == "GET" and path == TASK_PATH:
            return 200, {
                "task_id": 12,
                "run_id": "01ARUN",
                "workflow": "demo",
                "node": "build",
                "attempt": 1,
                "title": "a run",
                "description": "",
                "input": None,
                "output_schema": OUTPUT_SCHEMA,
                "log": [],
            }
        if request.method == "POST" and path == f"{TASK_PATH}/log":
            return 200, {"log_id": 7}
        if request.method == "POST" and path == f"{TASK_PATH}/submit":
            payload = request.json
            if isinstance(payload, dict) and "verdict" in payload:
                return 200, {"ok": True}
            return 422, {
                "errors": [{"loc": ["verdict"], "msg": "Field required"}],
                "schema": OUTPUT_SCHEMA,
            }
        if request.method == "POST" and path == f"{TASK_PATH}/ask":
            return 200, {"request_id": "01AREQ", "mode": "options"}
        if request.method == "GET" and path.startswith(f"{TASK_PATH}/requests/"):
            return 200, {"answered": True, "answer": "yes", "answered_by": "operator"}
        return 404, {"error": "not_found", "code": "not_found"}


@pytest.fixture
def task_api() -> Iterator[TaskAPI]:
    """A listening agent API on loopback, torn down with the test."""

    state = TaskAPI()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _respond(self, method: str) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length).decode() if length else ""
            status, payload = state.handle(
                Recorded(method, self.path, dict(self.headers), body)
            )
            encoded = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's name
            self._respond("GET")

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's name
            self._respond("POST")

        def log_message(self, format: str, *args: Any) -> None:
            """Keep the test output the test's."""

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    state.server = server
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def node_version() -> tuple[int, int]:
    """The node on ``PATH``, as ``(major, minor)``; ``(0, 0)`` for none."""

    binary = shutil.which("node")
    if binary is None:
        return (0, 0)
    reported = subprocess.run(
        [binary, "--version"], capture_output=True, text=True, check=True
    ).stdout.strip()
    major, minor, *_ = reported.lstrip("v").split(".")
    return int(major), int(minor)


#: Node strips TypeScript types on its own from 22.6, which is what lets
#: the probe import the extension with nothing else installed.
needs_node = pytest.mark.skipif(
    node_version() < (22, 6),
    reason="the extension probe needs node >= 22.6 (type stripping)",
)

needs_pi = pytest.mark.skipif(
    shutil.which("pi") is None, reason="pi is not installed on this machine"
)


def probe(
    *arguments: str, base: str | None = None, token: str = TOKEN
) -> dict[str, Any]:
    """Run ``probe_extension.mjs`` and parse what it printed."""

    environment = dict(os.environ)
    environment.pop("ATHANORE_TASK_URL", None)
    environment.pop("ATHANORE_TASK_TOKEN", None)
    if base is not None:
        environment["ATHANORE_TASK_URL"] = base
        environment["ATHANORE_TASK_TOKEN"] = token
    finished = subprocess.run(
        ["node", str(PROBE), str(ATHANORE_EXTENSION), *arguments],
        capture_output=True,
        text=True,
        env=environment,
        timeout=120,
    )
    assert finished.stdout, finished.stderr
    return json.loads(finished.stdout)


# --------------------------------------------------------------------------
# What the extension registers
# --------------------------------------------------------------------------


@needs_node
def test_the_five_tools_are_registered(task_api: TaskAPI) -> None:
    """08 §MCP's five, by name and in 19's order."""

    tools = probe(base=task_api.base)["tools"]
    assert [tool["name"] for tool in tools] == TOOLS


@needs_node
def test_the_descriptions_are_19s_wording(task_api: TaskAPI) -> None:
    """ "Tool descriptions carry the same wording as the 19 kickoff" (08).

    Not a byte comparison: 19's tier block is one sentence naming all
    five, and a tool description is that sentence's clause about one of
    them. What is pinned is that the clause is there — a model reading
    the tool list and a model reading the prompt are told the same thing.
    """

    tools = probe(base=task_api.base)["tools"]
    described = {tool["name"]: tool["description"] for tool in tools}
    assert "the FULL work log" in described["get_task"]
    assert "deliverables and notes from every earlier stage" in described["get_task"]
    assert "MUST be appended before you finish" in described["append_log"]
    assert "the next stage reads this same log" in described["append_log"]
    assert "this tool's input schema" in described["submit_result"]
    assert "sparingly" in described["ask_operator"]
    assert "Continue only once you have the answer" in described["wait_answer"]


@needs_node
def test_submit_result_shows_the_declared_schema(task_api: TaskAPI) -> None:
    """The task's ``output_schema`` **is** the tool's input schema (05, 08)."""

    tools = {tool["name"]: tool for tool in probe(base=task_api.base)["tools"]}
    assert tools["submit_result"]["parameters"] == OUTPUT_SCHEMA

    read = [one for one in task_api.requests if one.method == "GET"]
    assert [one.path for one in read] == [TASK_PATH], "the schema is fetched once"


@needs_node
def test_without_a_task_the_tools_still_register() -> None:
    """`pi` started by hand is not a failure; it is a pi with no task.

    The submission schema is permissive because the endpoint is the
    validator, and nothing is reported to the operator: there is no error
    here to swallow.
    """

    reported = probe()
    tools = {tool["name"]: tool for tool in reported["tools"]}
    assert list(tools) == TOOLS
    assert tools["submit_result"]["parameters"] == {
        "type": "object",
        "additionalProperties": True,
    }
    assert reported["notifications"] == []


@needs_node
def test_an_unreachable_athanore_is_reported_not_swallowed() -> None:
    """A schema that could not be read is said out loud, and pi still runs.

    The alternative — failing to start — would take a whole agent run
    down over the *shape* of its submission, which the endpoint would
    have told it anyway.
    """

    reported = probe(base="http://127.0.0.1:1/api/agent/tasks/12")
    tools = {tool["name"]: tool for tool in reported["tools"]}
    assert list(tools) == TOOLS
    assert tools["submit_result"]["parameters"]["additionalProperties"] is True

    (notification,) = reported["notifications"]
    assert notification["level"] == "warning"
    assert "submission schema could not be read" in notification["message"]


# --------------------------------------------------------------------------
# What the tools do
# --------------------------------------------------------------------------


@needs_node
def test_each_tool_calls_its_own_endpoint(task_api: TaskAPI) -> None:
    """One tier, one substrate: every tool is a call to 08's agent API."""

    calls: list[tuple[str, str]] = [
        ("get_task", "{}"),
        ("append_log", json.dumps({"text": "engineering: built it"})),
        ("submit_result", json.dumps({"verdict": "ship it"})),
        ("ask_operator", json.dumps({"prompt": "which one?", "options": ["a", "b"]})),
        ("wait_answer", json.dumps({"request_id": "01AREQ", "wait": 5})),
    ]
    for name, arguments in calls:
        answered = probe(name, arguments, base=task_api.base)
        assert "error" not in answered, (name, answered)

    # Every probe run fetches the schema first, so the calls under test
    # are what is left once those reads are taken out.
    seen = [(one.method, one.path.split("?")[0]) for one in task_api.requests]
    assert seen.count(("GET", TASK_PATH)) == len(calls) + 1, "get_task read it too"
    assert ("POST", f"{TASK_PATH}/log") in seen
    assert ("POST", f"{TASK_PATH}/submit") in seen
    assert ("POST", f"{TASK_PATH}/ask") in seen
    assert ("GET", f"{TASK_PATH}/requests/01AREQ") in seen

    posted = {one.path.split("?")[0]: one.json for one in task_api.requests if one.body}
    assert posted[f"{TASK_PATH}/log"] == {"text": "engineering: built it"}
    assert posted[f"{TASK_PATH}/submit"] == {"verdict": "ship it"}
    assert posted[f"{TASK_PATH}/ask"] == {
        "prompt": "which one?",
        "options": ["a", "b"],
    }

    waited = [one for one in task_api.requests if "/requests/" in one.path]
    assert waited[0].path.endswith("?wait=5")


@needs_node
def test_the_token_travels_in_the_header_and_nowhere_else(task_api: TaskAPI) -> None:
    """12 §Task tokens, checked against every request that was made."""

    probe("append_log", json.dumps({"text": "a line"}), base=task_api.base)
    assert task_api.requests
    for one in task_api.requests:
        assert one.headers.get("X-Athanore-Token") == TOKEN, one.path
        assert TOKEN not in one.path
        assert TOKEN not in one.body


@needs_node
def test_a_rejected_submission_comes_back_with_the_errors(task_api: TaskAPI) -> None:
    """The 422 body is the repair material, so it reaches the model (05).

    pi marks a tool result as an error when ``execute`` throws, and the
    message is what the model reads — so the errors and the schema have
    to be in it, not logged and dropped.
    """

    payload = json.dumps({"notes": "no verdict"})
    answered = probe("submit_result", payload, base=task_api.base)
    assert "error" in answered
    assert "HTTP 422" in answered["error"]
    assert "Field required" in answered["error"]
    assert "verdict" in answered["error"]


@needs_node
def test_a_tool_without_a_task_says_so(task_api: TaskAPI) -> None:
    """The failure names the two variables, because that is the fix."""

    answered = probe("append_log", json.dumps({"text": "a line"}))
    assert "ATHANORE_TASK_URL" in answered["error"]
    assert "ATHANORE_TASK_TOKEN" in answered["error"]
    assert task_api.requests == []


# --------------------------------------------------------------------------
# pi itself
# --------------------------------------------------------------------------


@needs_pi
def test_pi_loads_the_extension(tmp_path: Path) -> None:
    """The smoke the tier rests on: pi's own loader accepts the file.

    ``--mode rpc`` needs no model and no key to answer ``get_state``, and
    the async factory is awaited before startup continues — so a reply
    here means the extension parsed, ran, and registered its tools inside
    pi rather than inside the probe's stub.

    ``-ne`` turns off discovery so the run loads exactly the file in this
    checkout: the container mounts ``examples/pi/extensions`` at pi's own
    extension directory, and without it the same extension would be loaded
    twice and all five tool names would collide.
    """

    finished = subprocess.run(
        [
            "pi",
            "-ne",
            "-e",
            str(ATHANORE_EXTENSION),
            "--mode",
            "rpc",
            "--no-session",
            "--session-dir",
            str(tmp_path),
        ],
        input='{"type":"get_state","id":"1"}\n',
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert finished.returncode == 0, finished.stderr
    answers = [
        json.loads(line) for line in finished.stdout.splitlines() if line.strip()
    ]
    responses = [one for one in answers if one.get("command") == "get_state"]
    assert responses and responses[0]["success"] is True, finished.stdout
    assert not [one for one in answers if one.get("type") == "extension_error"]


@needs_pi
def test_a_broken_extension_would_have_failed_this(tmp_path: Path) -> None:
    """The smoke above is only worth running if this one fails pi."""

    broken = tmp_path / "broken.ts"
    broken.write_text("export default function (pi) { this is not typescript }\n")
    finished = subprocess.run(
        [
            "pi",
            "-ne",
            "-e",
            str(broken),
            "--mode",
            "rpc",
            "--no-session",
            "--session-dir",
            str(tmp_path),
        ],
        input='{"type":"get_state","id":"1"}\n',
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert finished.returncode != 0
    assert "Failed to load extension" in finished.stderr


# --------------------------------------------------------------------------
# The other side of the tier: the prompt
# --------------------------------------------------------------------------


async def test_the_native_prompt_carries_no_curl_and_no_token(
    context: Callable[..., Awaitable[TaskContext]],
) -> None:
    """What the tier is for: the token never reaches the model (12, 05).

    Rendered from the example seat rather than from a test double, so
    what is asserted is the prompt a pi agent is actually handed.
    """

    ctx = await context("a run")
    assert PiAgent.tooling == "native", "the tier this test is about"
    rendered = await PiAgent().render_prompt("do the work", ctx, tier="native")

    assert "curl" not in rendered
    assert ctx.token not in rendered
    assert "X-Athanore-Token" not in rendered
    for name in TOOLS[:3]:
        assert name in rendered
    assert "Work on task" in rendered


async def test_the_http_tier_would_have_carried_both(
    context: Callable[..., Awaitable[TaskContext]],
) -> None:
    """The control: the same seat in the fallback tier is curl and a token."""

    ctx = await context("a run")
    rendered = await PiAgent().render_prompt("do the work", ctx, tier="http")

    assert "curl" in rendered
    assert ctx.token in rendered

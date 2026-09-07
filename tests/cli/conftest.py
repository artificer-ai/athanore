"""A live server, and the CLI pointed at it (T054, T054a).

The two verb files test `athanore` the way an operator runs it: the real
typer application, over a real socket, against a real `Server` with a
real store behind it. Nothing here is mocked, and that is the point —
the CLI is the second client of the one wire contract (02 §One wire
contract), so a verb that cannot be written against the running API is a
gap in the API rather than something to reach around in a fixture.

Two things about the shape of these tests are load-bearing.

**The CLI runs in a thread.** `athanore.cli.main` is synchronous and its
client is `httpx.Client`; called on the event loop it would block the
server it is talking to and deadlock. `asyncio.to_thread` is the whole
fix: the verb blocks a worker thread while the loop goes on serving.

**A follower is waited for, not slept on.** `-f` and `--watch` connect to
`GET /api/events`, and a test that emitted its event before that
connection existed would be a test that passes when it is lucky. The bus
records its subscribers, and the SSE endpoint subscribes before it
replays (`athanore.api.sse`), so "the follower is listening" is an
observable fact and :func:`listening` waits for it.

Setting a test up and checking what it did go through :class:`Api` — a
plain `httpx` client on the same server — and never through a second CLI
invocation. Two reasons, and both are about telling the truth: what a
steering verb did has to be **visible through the API** (17 §T054a), so
reading it back through the same client that wrote it would prove
nothing; and `capsys` is one buffer per process, so a CLI call made while
a follower is running would drain the follower's output into somebody
else's assertion.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
import structlog
from pydantic import BaseModel, Field

from athanore.cli import main
from athanore.engine import Pool
from athanore.engine.context import current_task
from athanore.requests.human import human_input
from athanore.server import Server
from athanore.settings import AthanoreSettings
from athanore.store.rows import ChunkKind, LogAuthor
from athanore.workflow import Workflow

#: How long a wait for something the server has to do may take before the
#: test fails instead of hanging. Generous for a loopback server, finite
#: so a stuck follower fails one test rather than the gate.
DEADLINE = 30.0

#: The prompt every `human_input` in this file asks.
PROMPT = "Ship it?"

#: An `options` request shaped like an ACP permission, so `permit` and
#: `deny` have kinds to choose between (20 §Finding 1). Rejection first,
#: which is the order the adapter uses and the order that must not decide
#: the answer.
PERMISSION_OPTIONS = [
    {"option_id": "no", "name": "Deny", "kind": "reject_once"},
    {"option_id": "no-always", "name": "Always Deny", "kind": "reject_always"},
    {"option_id": "yes", "name": "Allow Once", "kind": "allow_once"},
    {"option_id": "yes-always", "name": "Always Allow", "kind": "allow_always"},
]


#: An `options` request whose choices carry no kind, which is what most
#: `human_input(options=[...])` questions look like. `permit` and `deny`
#: cannot pick from these, and that refusal is theirs to word.
PLAIN_OPTIONS = ["approve", "reject"]


class Signoff(BaseModel):
    """The model a `form` request is opened from."""

    verdict: str = Field(description="ship or hold")


# --------------------------------------------------------------------------
# The workflows the verbs are exercised against
# --------------------------------------------------------------------------


def demo_workflow(name: str = "demo") -> Workflow:
    """Two nodes that run to completion, writing a log and a transcript."""

    wf = Workflow(name)

    @wf.node(start=True)
    async def plan(review):
        """Read the task and decide what to do."""

        services = current_task().services
        await services.log.append("planned it", author=LogAuthor.agent)
        await services.stream.append(ChunkKind.text, "reading the task")
        await services.stream.append(ChunkKind.thought, "this looks easy")
        await services.stream.flush()
        return review

    @wf.node()
    async def review() -> str:
        """Look at what the plan produced."""

        return "shipped"

    return wf


def parked_workflow(name: str = "parked") -> Workflow:
    """One node that never finishes, so a run stays `running` to be steered."""

    wf = Workflow(name)

    @wf.node(start=True)
    async def hold() -> str:
        await asyncio.sleep(DEADLINE * 10)
        return "never"

    return wf


def asking_workflow(name: str, **question: Any) -> Workflow:
    """One node that asks the operator and returns their answer.

    The keyword arguments are ``human_input``'s, so the same factory
    builds the ``text``, ``options`` and ``form`` request the three
    shapes of ``answer`` are about (06 §The model).
    """

    wf = Workflow(name)

    @wf.node(start=True)
    async def ask():
        answer = await human_input(PROMPT, **question)
        return answer.model_dump() if isinstance(answer, BaseModel) else answer

    return wf


def chatty_workflow(name: str = "chatty") -> Workflow:
    """A node that streams, waits for an answer, then streams again.

    The one workflow that makes ``stream -f`` a real test: the attempt is
    `waiting` — which is live, because a waiting attempt goes on writing
    once its request is answered — so a follower attaches to a transcript
    that is genuinely still growing.
    """

    wf = Workflow(name)

    @wf.node(start=True)
    async def talk():
        services = current_task().services
        await services.stream.append(ChunkKind.text, "first thing")
        await services.stream.flush()
        answer = await human_input(PROMPT)
        await services.stream.append(ChunkKind.text, "second thing")
        await services.stream.flush()
        return answer

    return wf


def workflows() -> list[tuple[Workflow, Pool | None]]:
    """Every workflow a CLI test may reach, and the pool it runs on.

    `parked` gets the `holding` pool to itself because its node holds its slot for
    the length of the test; on the default pool it would be a test that
    stops every other run in the file from dispatching.
    """

    return [
        (demo_workflow(), None),
        (chatty_workflow(), None),
        (asking_workflow("ask_text"), None),
        (asking_workflow("ask_options", options=PERMISSION_OPTIONS), None),
        (asking_workflow("ask_plain", options=PLAIN_OPTIONS), None),
        (asking_workflow("ask_form", output_model=Signoff), None),
        (parked_workflow(), Pool("holding", 2)),
    ]


# --------------------------------------------------------------------------
# The server
# --------------------------------------------------------------------------


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """An environment the developer's own installation cannot reach into.

    Every `ATHANORE_*` is dropped and `XDG_CONFIG_HOME` is moved, because
    the client resolves its url and token from exactly those two places
    (11 §Client connection) and a suite that read the machine would be
    testing the machine. `COLUMNS` is set because rich sizes a table to
    the terminal, and 80 columns of pytest capture would fold the cells
    these tests read.
    """

    for name in [key for key in os.environ if key.startswith("ATHANORE_")]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("COLUMNS", "200")
    yield


@pytest.fixture
async def server(tmp_path: Path, isolated: None) -> AsyncIterator[Server]:
    """A started server on a free port, with every test workflow on it."""

    settings = AthanoreSettings(
        root_path=tmp_path,
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'athanore.db'}",
        host="127.0.0.1",
        port=0,
        workers=4,
    )
    instance = Server(settings)
    for workflow, pool in workflows():
        instance.register(workflow, pool)
    await instance.start()
    try:
        yield instance
    finally:
        await instance.stop()
        # `Server.start` configures logging against whatever `sys.stderr`
        # was when it ran, and pytest swaps that stream between phases.
        structlog.reset_defaults()
        logging.getLogger().handlers.clear()


# --------------------------------------------------------------------------
# The CLI
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Result:
    """What one CLI invocation exited with and printed."""

    code: int
    out: str
    err: str


@dataclass
class Cli:
    """The CLI, pointed at a server, run off the event loop."""

    url: str
    capsys: pytest.CaptureFixture[str]

    def args(self, argv: Sequence[str], *, json: bool = False) -> list[str]:
        """``argv`` with the connection flags the operator would have set.

        ``--json`` goes before the verb because it is the application's
        flag and not any verb's (11 §Client connection).
        """

        return ["--url", self.url, *(["--json"] if json else []), *argv]

    async def run(self, *argv: str, json: bool = False) -> Result:
        """Run one verb to completion and collect what it said."""

        code = await asyncio.to_thread(main, self.args(argv, json=json))
        captured = self.capsys.readouterr()
        return Result(code, captured.out, captured.err)

    async def json(self, *argv: str) -> Any:
        """Run one verb with ``--json`` and decode what it printed."""

        import json as json_module

        result = await self.run(*argv, json=True)
        assert result.code == 0, f"{argv} exited {result.code}: {result.err}"
        return json_module.loads(result.out)

    def follower(self, *argv: str, json: bool = False) -> asyncio.Task[int]:
        """Start a following verb in a thread and hand back its task.

        The caller awaits it after making the server do something and
        after ending the stream; :meth:`Cli.run`'s capture is deliberately
        not used, because a follower's output is only whole once it has
        stopped writing.
        """

        return asyncio.create_task(asyncio.to_thread(main, self.args(argv, json=json)))


@pytest.fixture
def cli(server: Server, capsys: pytest.CaptureFixture[str]) -> Cli:
    """The CLI, aimed at the started server."""

    return Cli(url=server.url, capsys=capsys)


class Api:
    """The API as a test reads it: setup, and what a verb actually did.

    Deliberately not the CLI's own client. What a steering verb changed
    has to be visible through the wire contract to anybody, so a test
    that asked the CLI whether the CLI worked would be asserting the
    round trip of one code path against itself.
    """

    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http

    async def get(self, path: str, **params: Any) -> Any:
        response = await self._http.get(path, params=params)
        response.raise_for_status()
        return response.json()

    async def post(self, path: str, body: Any = None) -> Any:
        response = await self._http.post(path, json=body)
        response.raise_for_status()
        return None if response.status_code == 204 else response.json()

    async def submit(self, workflow: str, title: str, description: str = "") -> str:
        """Queue a run and return its id."""

        created = await self.post(
            f"/api/workflows/{workflow}/runs",
            {"title": title, "description": description},
        )
        return str(created["run_id"])

    async def run(self, run_id: str) -> dict[str, Any]:
        return await self.get(f"/api/runs/{run_id}")

    async def status(self, run_id: str) -> str:
        return str((await self.run(run_id))["status"])

    async def is_status(self, run_id: str, *statuses: str) -> bool:
        """Whether the run is in one of ``statuses`` right now.

        A coroutine, so it composes with :func:`until`: a predicate that
        compared ``status(...)`` to a string would be comparing a
        coroutine object and would never be true.
        """

        return await self.status(run_id) in statuses

    async def task(self, task_id: int) -> dict[str, Any]:
        return await self.get(f"/api/tasks/{task_id}")

    async def requests(self, run_id: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"pending": "true"}
        if run_id is not None:
            params["run"] = run_id
        return await self.get("/api/requests", **params)

    async def events(self, run_id: str) -> list[dict[str, Any]]:
        return await self.get(f"/api/runs/{run_id}/events", limit=5000)

    async def completed(self, workflow: str, title: str, description: str = "") -> str:
        """Submit a run and wait until it has finished."""

        run_id = await self.submit(workflow, title, description)
        await until(
            lambda: self.is_status(run_id, "completed"),
            what=f"run {run_id} of {workflow} to complete",
        )
        return run_id

    async def one_request(self, workflow: str) -> dict[str, Any]:
        """Submit a run that asks a question, and return the request."""

        run_id = await self.submit(workflow, "Needs a person")
        views = await until(
            lambda: self.requests(run_id), what=f"a request from {workflow}"
        )
        return views[0]


@pytest.fixture
async def api(server: Server) -> AsyncIterator[Api]:
    """A plain HTTP client on the server, for setting up and checking."""

    async with httpx.AsyncClient(base_url=server.url, timeout=DEADLINE) as http:
        yield Api(http)


# --------------------------------------------------------------------------
# Waiting
# --------------------------------------------------------------------------


async def until(
    predicate: Callable[[], Any | Awaitable[Any]],
    *,
    what: str = "the condition",
    deadline: float = DEADLINE,
) -> Any:
    """Poll ``predicate`` until it is truthy, then return what it gave.

    Every wait in these tests goes through here so that none of them is a
    `sleep` that happens to be long enough: a server that never reaches
    the state fails the test with what was being waited for, at the
    deadline, instead of at whatever the next assertion happened to be.
    """

    ends_at = time.monotonic() + deadline
    while True:
        value = predicate()
        if asyncio.iscoroutine(value):
            value = await value
        if value:
            return value
        if time.monotonic() > ends_at:
            raise AssertionError(f"timed out after {deadline}s waiting for {what}")
        await asyncio.sleep(0.02)


def flat(text: str) -> str:
    """``text`` with its whitespace collapsed, for asserting on a message.

    Rich wraps what it prints to the width of the terminal, so a sentence
    the CLI wrote as one line arrives as several. Every assertion about a
    *message* goes through here; assertions about a *table* do not, since
    the columns are the point of those.
    """

    return " ".join(text.split())


async def listening(server: Server, before: int) -> None:
    """Wait until one more client is subscribed to the event bus than ``before``.

    The SSE endpoint subscribes *before* it replays, so a subscription
    appearing is the follower having connected — the fact a test needs
    before it makes the event it expects to see followed.
    """

    await until(
        lambda: len(server.bus.subscriptions) > before,
        what="a follower to subscribe to the event stream",
    )

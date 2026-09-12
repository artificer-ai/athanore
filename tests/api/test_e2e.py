"""The whole system through the wire it publishes (T055, A3.11).

The port of the MVP's `test_e2e.py` and `test_api_surface.py`, and the
only suite in the tree that has every layer in it at once: a real
`Server` on a real socket, a real store, the engine dispatching, agents
submitting over HTTP with their task tokens, and the API and the event
stream as the only things a test is allowed to look at.

That last clause is what makes it an end-to-end suite rather than a
slower engine test. `tests/engine` reads the store back and
`tests/api/conftest.py` never starts a dispatch loop, both on purpose;
here nothing is read except through the API, because "one wire contract"
(02) is a claim about what a client can see and the only way to check it
is to be one.

Three shapes are exercised, and they are the three the MVP's file had:

- **a run to completion**, with a loop-back in the middle — the review
  agent asks for changes once and approves the second time — observed on
  `GET /api/events` *while it happens* and then read back through
  `GET /api/runs/{id}`. The two must agree;
- **a fan-out**, driven entirely from the API, ending with one run whose
  `outputs` carry both branches in branch order (D58);
- **a request answered through the API**: a node body asks a person, the
  question appears in the inbox, `POST /api/requests/{id}/answer` frees
  the attempt, and the answer comes back as the run's output.

The API-surface half of the MVP's second file is the last section:
health, OpenAPI, the docs page, and one probe per refusal — an unknown
run, an unknown workflow, a body with no title, and an agent endpoint
presented with the wrong task token. v1's error model is 08's
`{"error", "code"}` rather than v0's bare `{"error"}`, and a bad body is
a 422 rather than a 400, so those are asserted in the v1 shape.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import httpx
import pytest
import structlog
from pydantic import BaseModel

from athanore.api.sse import RESYNC
from athanore.engine import Pool
from athanore.requests.human import human_input
from athanore.server import Server
from athanore.settings import AthanoreSettings
from athanore.testing import MockAgent
from athanore.workflow import Workflow

#: How long anything this suite waits for may take before the test fails
#: instead of hanging. Generous for a loopback server under a cold
#: container, finite so a deadlock costs one test rather than the gate.
DEADLINE = 30.0

#: The question the `asking` workflow puts to the operator.
PROMPT = "Ship it?"

#: What the `pipe` workflow's first agent streams, as `(kind, text)`
#: pairs. It is here so that the run carries the one event that is
#: published and never stored — `task.stream` (03) — and the stream test
#: can say what the wire does with it.
TRANSCRIPT = [("text", "reading the brief"), ("thought", "this looks easy")]


# --------------------------------------------------------------------------
# The workflows
# --------------------------------------------------------------------------


class ReviewDecision(BaseModel):
    """What the review agent submits (05 §Submissions)."""

    verdict: Literal["approve", "changes_requested"]
    feedback: str = ""


class Reviewer(MockAgent):
    """A double that submits a `ReviewDecision` and nothing else."""

    output_model = ReviewDecision


def pipe() -> Workflow:
    """The MVP's end-to-end shape: brief, build, review, ship.

    The review node routes on what its agent *submitted*, which is the
    architecture rule the whole file is here to exercise — the agent
    submits a value and the body decides where the work goes. The first
    review asks for changes, so `build` and `review` each run twice.
    """

    wf = Workflow("pipe")
    verdicts = ["changes_requested", "approve"]

    @wf.node(start=True)
    async def brief(build):
        """Read the operator's brief and hand it on."""

        await MockAgent(log="intake: reworded the brief", stream=TRANSCRIPT).run()
        return build

    @wf.node()
    async def build(review):
        """Do the work, then send it for review."""

        await MockAgent(log="engineering: built it, tests green").run()
        return review

    @wf.node()
    async def review(build, ship):
        """Approve, or send the work back a stage."""

        agent = Reviewer(
            submit=lambda: {"verdict": verdicts.pop(0), "feedback": "please fix"},
            log="review: findings posted",
        )
        result = await agent.run()
        if result.output.verdict == "approve":
            return ship
        return build

    @wf.node()
    async def ship():
        """Ship it, and end the run."""

        await MockAgent(log="git: shipped it").run()
        return "shipped"

    return wf


def fan() -> Workflow:
    """One stage splits into two branches that each run to the end."""

    wf = Workflow("fan")

    @wf.node(start=True)
    async def intake(split):
        return split

    @wf.node()
    async def split(build):
        return [build("deliverable #1"), build("deliverable #2")]

    @wf.node()
    async def build(done, *, item):
        await MockAgent(log=f"built {item}").run()
        return done(item)

    @wf.node()
    async def done(*, item):
        return item

    return wf


def asking() -> Workflow:
    """One node that asks a person and returns what they said."""

    wf = Workflow("asking")

    @wf.node(start=True)
    async def ask():
        return await human_input(PROMPT)

    return wf


# --------------------------------------------------------------------------
# The server
# --------------------------------------------------------------------------


@pytest.fixture
def isolated(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Every `ATHANORE_*` dropped, so the shell cannot change an assertion.

    `public_url` matters most: it is what an agent submits against, and a
    value exported into the container would point every `MockAgent` in
    this file at a server that is not the one under test.
    """

    for name in [key for key in os.environ if key.startswith("ATHANORE_")]:
        monkeypatch.delenv(name, raising=False)
    yield


@pytest.fixture
async def server(tmp_path: Path, isolated: None) -> AsyncIterator[Server]:
    """A started server on a free port, running every workflow in this file.

    `fan` gets a pool of its own so that its two branches are in flight
    together; the rest share the default pool, which is where a run that
    is waiting for a person has to release its slot.
    """

    settings = AthanoreSettings(
        root_path=tmp_path,
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'athanore.db'}",
        host="127.0.0.1",
        port=0,
        workers=2,
    )
    instance = Server(settings)
    instance.register(pipe())
    instance.register(fan(), Pool("wide", 4))
    instance.register(asking())
    await instance.start()
    try:
        yield instance
    finally:
        await instance.stop()
        # `Server.start` configures logging against whatever `sys.stderr`
        # was when it ran, and pytest swaps that stream between phases.
        structlog.reset_defaults()
        logging.getLogger().handlers.clear()


@pytest.fixture
async def http(server: Server) -> AsyncIterator[httpx.AsyncClient]:
    """A plain HTTP client on the running server: the only way in."""

    async with httpx.AsyncClient(base_url=server.url, timeout=DEADLINE) as client:
        yield client


# --------------------------------------------------------------------------
# Waiting, and the one thing a test reads that is not a response body
# --------------------------------------------------------------------------


async def until(predicate: Callable[[], Awaitable[Any] | Any], *, what: str) -> Any:
    """Poll ``predicate`` until it is truthy, or fail naming what was awaited."""

    ends_at = time.monotonic() + DEADLINE
    while True:
        value = predicate()
        if asyncio.iscoroutine(value):
            value = await value
        if value:
            return value
        if time.monotonic() > ends_at:
            raise AssertionError(f"timed out after {DEADLINE}s waiting for {what}")
        await asyncio.sleep(0.02)


async def submit(
    http: httpx.AsyncClient, workflow: str, title: str, **body: Any
) -> str:
    """`POST /api/workflows/{workflow}/runs`, returning the run id."""

    response = await http.post(
        f"/api/workflows/{workflow}/runs", json={"title": title, **body}
    )
    assert response.status_code == 201, response.text
    return str(response.json()["run_id"])


async def run_of(http: httpx.AsyncClient, run_id: str) -> dict[str, Any]:
    """`GET /api/runs/{id}`, raising on anything but a 200."""

    response = await http.get(f"/api/runs/{run_id}")
    assert response.status_code == 200, response.text
    return dict(response.json())


async def finished(http: httpx.AsyncClient, run_id: str) -> dict[str, Any]:
    """Wait for a run to reach a terminal status, and return it."""

    return await until(lambda: _ended(http, run_id), what=f"run {run_id} to finish")


async def _ended(http: httpx.AsyncClient, run_id: str) -> dict[str, Any] | None:
    run = await run_of(http, run_id)
    return run if run["status"] in ("completed", "failed", "cancelled") else None


async def stored_events(http: httpx.AsyncClient, run_id: str) -> list[dict[str, Any]]:
    """`GET /api/runs/{id}/events`, the history the stream replays from."""

    response = await http.get(f"/api/runs/{run_id}/events", params={"limit": 5000})
    assert response.status_code == 200, response.text
    return list(response.json())


@dataclass
class Frames:
    """The frames one `GET /api/events` connection has delivered so far.

    A live reader rather than a fetch: the completion of a run has to be
    seen *arriving*, which a request that returns a finished body cannot
    show. What is kept is the `EventEnvelope` of each `data:` line — the
    same object `GET /api/runs/{id}/events` returns (18 §Typing) — so the
    two histories can be compared without either being translated first.

    `resyncs` counts the control frames of 08 §Events. Nothing in this
    file should provoke one, and a test that saw one would otherwise
    quietly assert on a history with a hole in it.
    """

    seen: list[dict[str, Any]] = field(default_factory=list)
    resyncs: int = 0

    def add(self, name: str, payload: Any, event_id: int | None) -> None:
        if name == RESYNC:
            self.resyncs += 1
            return
        assert isinstance(payload, dict), payload
        # The `id:` line is the reconnect cursor and the envelope carries
        # the same id; an ephemeral `task.stream` has neither (08
        # §Events), so one comparison covers both cases.
        assert payload.get("id") == event_id, payload
        self.seen.append(payload)

    def names(self, run_id: str) -> list[str]:
        """The event names seen for one run, in arrival order."""

        return [event["name"] for event in self.seen if event.get("run_id") == run_id]

    def nodes(self, run_id: str, name: str) -> list[str]:
        """The `node` of every ``name`` event seen for one run."""

        return [
            event["data"]["node"]
            for event in self.seen
            if event.get("run_id") == run_id and event["name"] == name
        ]

    def has(self, run_id: str, name: str) -> bool:
        return name in self.names(run_id)


@pytest.fixture
async def frames(
    server: Server, http: httpx.AsyncClient
) -> AsyncIterator[Callable[[], Awaitable[Frames]]]:
    """Open the event stream and start collecting, on demand.

    Returns an awaitable that resolves once the connection is **listening**
    — the endpoint subscribes to the bus before it replays, so a new
    subscription is the observable fact that the stream is attached — and
    that is what a test waits for before it makes the events it expects
    to see. Connecting afterwards would be a test that passes when it is
    lucky.
    """

    collected = Frames()
    reader: asyncio.Task[None] | None = None

    async def open_stream() -> Frames:
        nonlocal reader
        before = len(server.bus.subscriptions)
        reader = asyncio.create_task(_read(http, collected))
        await until(
            lambda: len(server.bus.subscriptions) > before,
            what="the event stream to subscribe",
        )
        return collected

    yield open_stream
    if reader is not None:
        reader.cancel()
        try:
            await reader
        except asyncio.CancelledError:
            pass


async def _read(http: httpx.AsyncClient, into: Frames) -> None:
    """Stream `GET /api/events` into ``into`` until cancelled."""

    async with http.stream(
        "GET", "/api/events", timeout=httpx.Timeout(DEADLINE, read=None)
    ) as response:
        assert response.status_code == 200, response.status_code
        assert response.headers["content-type"].startswith("text/event-stream")
        name: str | None = None
        data: list[str] = []
        event_id: int | None = None
        async for line in response.aiter_lines():
            if not line:
                if name is not None:
                    into.add(name, _decode(data), event_id)
                name, data, event_id = None, [], None
                continue
            if line.startswith(":"):
                continue
            field_, _, value = line.partition(":")
            value = value[1:] if value.startswith(" ") else value
            if field_ == "event":
                name = value
            elif field_ == "data":
                data.append(value)
            elif field_ == "id":
                event_id = int(value)


def _decode(data: list[str]) -> Any:
    """The `data:` lines of one frame, rejoined and parsed."""

    joined = "\n".join(data)
    return json.loads(joined) if joined else None


# --------------------------------------------------------------------------
# A run, end to end, through the API and the stream
# --------------------------------------------------------------------------


async def test_a_run_completes_and_the_api_and_the_stream_agree(
    http: httpx.AsyncClient, frames: Callable[[], Awaitable[Frames]]
) -> None:
    """The MVP's `test_end_to_end`, on v1's wire.

    The stream is attached first, so every event of the run is seen
    arriving; the run is then submitted, run and read back. What the
    stream delivered and what the store hands out over REST have to be
    the same history, because they are serialised through one envelope
    (18 §Typing) and a client that caught up over one and continued on
    the other must not see a seam.
    """

    live = await frames()
    run_id = await submit(http, "pipe", "build feature xyz", description="the details")

    # Completion observed on the stream, live...
    await until(
        lambda: live.has(run_id, "run.completed"),
        what=f"run.completed for {run_id} on the event stream",
    )
    # ...and through the API.
    run = await finished(http, run_id)
    assert run["status"] == "completed"
    assert run["output"] == "shipped"

    # One loop-back, then approval: `build` and `review` each ran twice.
    nodes = [task["node"] for task in run["tasks"]]
    assert nodes == ["brief", "build", "review", "build", "review", "ship"]
    assert all(task["status"] == "done" for task in run["tasks"])

    # The work log carries every station's handoff, as the MVP's did.
    log = await http.get(f"/api/runs/{run_id}/log")
    assert log.status_code == 200, log.text
    texts = [entry["text"] for entry in log.json()]
    assert "intake: reworded the brief" in texts
    assert texts.count("engineering: built it, tests green") == 2
    assert texts.count("review: findings posted") == 2
    assert "git: shipped it" in texts

    # The two agent submissions were accepted by the agent API, which is
    # the round trip `MockAgent` makes with its task token.
    stored = await stored_events(http, run_id)
    assert [event["name"] for event in stored].count("submission.accepted") == 2

    # The stream and the stored history are one history: same names, in
    # the same order, once the one ephemeral event is taken out.
    # `task.stream` is published and never stored (03), which is why it
    # is the one frame that carries no `id:` — asserted for every frame
    # in `Frames.add`, and visible here as the difference between the two
    # lists.
    live_names = live.names(run_id)
    assert "task.stream" in live_names
    assert [name for name in live_names if name != "task.stream"] == [
        event["name"] for event in stored
    ]
    assert live.nodes(run_id, "task.started") == nodes
    assert live.resyncs == 0

    # And the transcript the ephemeral event announced is readable at the
    # cursor it carried.
    transcript = await http.get(f"/api/tasks/{run['tasks'][0]['id']}/stream")
    assert transcript.status_code == 200, transcript.text
    page = transcript.json()
    assert [(chunk["kind"], chunk["text"]) for chunk in page["chunks"]] == TRANSCRIPT
    assert page["live"] is False


async def test_the_stream_carries_ids_the_store_can_replay_from(
    http: httpx.AsyncClient, frames: Callable[[], Awaitable[Frames]]
) -> None:
    """A client that reconnects with the last id it saw misses nothing.

    The seam of 08 §Events, exercised the way a browser exercises it: read
    part of a run live, drop the connection, and reconnect with `after=`.
    The two halves together have to be the whole run, once each.
    """

    live = await frames()
    run_id = await submit(http, "pipe", "reconnect")
    await until(
        lambda: live.has(run_id, "run.completed"), what="the run to finish live"
    )
    stored = await stored_events(http, run_id)

    # Replay from the middle of the run: everything after that id, and
    # nothing at or below it.
    cut = stored[len(stored) // 2]["id"]
    response = await http.get(
        f"/api/runs/{run_id}/events", params={"after": cut, "limit": 5000}
    )
    assert response.status_code == 200, response.text
    assert [event["id"] for event in response.json()] == [
        event["id"] for event in stored if event["id"] > cut
    ]


# --------------------------------------------------------------------------
# Fan-out, driven from the API
# --------------------------------------------------------------------------


async def test_a_fan_out_runs_every_branch_and_reports_both(
    http: httpx.AsyncClient,
) -> None:
    """The MVP's fan-out, submitted and read back over HTTP only.

    Both branches run, the run ends once when the last one lands, and its
    `outputs` are in branch order rather than arrival order (D58) — which
    is the property that makes a fan-out's result reproducible and is
    therefore the one worth asserting through the wire.
    """

    run_id = await submit(http, "fan", "do two things", description="a and b")
    run = await finished(http, run_id)

    assert run["status"] == "completed"
    nodes = sorted(task["node"] for task in run["tasks"])
    assert nodes == ["build", "build", "done", "done", "intake", "split"]
    assert all(task["status"] == "done" for task in run["tasks"])

    # Each branch carried its own payload the whole way down.
    built = sorted(task["payload"] for task in run["tasks"] if task["node"] == "build")
    assert built == ["deliverable #1", "deliverable #2"]

    # One `outputs` entry per terminal task, each carrying the branch it
    # came out of; `output` is the same values in **branch** order rather
    # than in the order the branches landed, which is what makes a
    # fan-out's result reproducible (D58).
    assert {
        entry["branch"][-1]["index"]: entry["value"] for entry in run["outputs"]
    } == {0: "deliverable #1", 1: "deliverable #2"}
    assert run["output"] == ["deliverable #1", "deliverable #2"]

    # The run completed once, naming both terminal tasks.
    completed = [
        event
        for event in await stored_events(http, run_id)
        if event["name"] == "run.completed"
    ]
    assert len(completed) == 1
    assert len(completed[0]["data"]["terminal_tasks"]) == 2


# --------------------------------------------------------------------------
# A request, answered through the API
# --------------------------------------------------------------------------


async def test_a_request_is_answered_through_the_api(
    http: httpx.AsyncClient,
) -> None:
    """A node body asks a person; the inbox and one POST are the answer.

    The attempt is `waiting` while the question is open — which is the
    status that released its pool slot (04 §Waiting) — and the answer is
    what the body returns, so the run's output is what the operator
    typed.
    """

    run_id = await submit(http, "asking", "needs a person")

    pending = await until(
        lambda: _inbox(http, run_id), what="the question to reach the inbox"
    )
    assert len(pending) == 1
    question = pending[0]
    assert question["prompt"] == PROMPT
    assert question["mode"] == "text"
    assert question["node"] == "ask"
    assert question["run_id"] == run_id

    # The attempt is parked, not running, and it says so on the wire.
    task = await http.get(f"/api/tasks/{question['task_id']}")
    assert task.status_code == 200, task.text
    assert task.json()["status"] == "waiting"

    answered = await http.post(
        f"/api/requests/{question['id']}/answer", json={"value": "yes, ship it"}
    )
    assert answered.status_code == 200, answered.text
    assert answered.json()["answer"] == "yes, ship it"

    run = await finished(http, run_id)
    assert run["status"] == "completed"
    assert run["output"] == "yes, ship it"

    # The inbox is empty again, and the history says the request was
    # opened and answered.
    assert await _inbox(http, run_id) == []
    names = [event["name"] for event in await stored_events(http, run_id)]
    assert names.count("request.opened") == 1
    assert names.count("request.answered") == 1


async def test_a_request_cannot_be_answered_twice(http: httpx.AsyncClient) -> None:
    """The second answer is a 409, not a silent overwrite (06 §Errors)."""

    run_id = await submit(http, "asking", "answered once")
    pending = await until(
        lambda: _inbox(http, run_id), what="the question to reach the inbox"
    )
    request_id = pending[0]["id"]

    first = await http.post(f"/api/requests/{request_id}/answer", json={"value": "yes"})
    assert first.status_code == 200, first.text
    second = await http.post(f"/api/requests/{request_id}/answer", json={"value": "no"})
    assert second.status_code == 409, second.text
    assert second.json()["code"] == "already_answered"

    run = await finished(http, run_id)
    assert run["output"] == "yes"


async def _inbox(http: httpx.AsyncClient, run_id: str) -> list[dict[str, Any]]:
    """The requests of one run that are still waiting on a person."""

    response = await http.get(
        "/api/requests", params={"pending": "true", "run": run_id}
    )
    assert response.status_code == 200, response.text
    return list(response.json())


# --------------------------------------------------------------------------
# The API surface (`test_api_surface.py`)
# --------------------------------------------------------------------------


async def test_health_reports_the_pools_and_the_work_in_flight(
    http: httpx.AsyncClient,
) -> None:
    """The MVP's health probe, in v1's shape (08 §System)."""

    response = await http.get("/api/health")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["version"]
    assert body["runs_running"] == 0
    assert body["tasks_in_progress"] == 0
    assert {name: pool["capacity"] for name, pool in body["pools"].items()} == {
        "default": 2,
        "wide": 4,
    }

    # `in_flight` is polled rather than read once. The loop takes a
    # pool's free slots *before* it claims and gives the surplus back
    # after (D107), so a probe that lands inside the claim's await sees
    # a reservation about to be returned — the whole `wide` pool, on a
    # cold runner's first tick. The assertion is that the server is
    # idle, which is what the poll says (D112).
    async def pools_idle() -> bool:
        pools = (await http.get("/api/health")).json()["pools"]
        return all(pool["in_flight"] == 0 for pool in pools.values())

    await until(pools_idle, what="every pool to read nothing in flight")

    # A run that finished leaves nothing in flight, which is what makes
    # this endpoint a drain check (04 §Shutdown).
    run_id = await submit(http, "pipe", "drain")
    await finished(http, run_id)
    body = (await http.get("/api/health")).json()
    assert body["runs_running"] == 0
    assert body["tasks_in_progress"] == 0


async def test_the_openapi_document_and_the_docs_page_are_served(
    http: httpx.AsyncClient,
) -> None:
    """The generated contract is the one the SPA and the CLI are built on."""

    response = await http.get("/openapi.json")
    assert response.status_code == 200, response.text
    paths = response.json()["paths"]
    for path in (
        "/api/health",
        "/api/workflows",
        "/api/workflows/{name}/runs",
        "/api/runs",
        "/api/runs/{run_id}",
        "/api/requests/{request_id}/answer",
        "/api/agent/tasks/{task_id}/submit",
        "/api/events",
    ):
        assert path in paths, path

    docs = await http.get("/docs")
    assert docs.status_code == 200
    assert "text/html" in docs.headers["content-type"]


async def test_the_workflow_list_names_what_the_server_registered(
    http: httpx.AsyncClient,
) -> None:
    """`GET /api/workflows` is how a client learns what it can submit."""

    response = await http.get("/api/workflows")
    assert response.status_code == 200, response.text
    assert sorted(entry["name"] for entry in response.json()) == [
        "asking",
        "fan",
        "pipe",
    ]


async def test_an_unknown_run_is_a_404_with_a_code(http: httpx.AsyncClient) -> None:
    """v0 answered `{"error": ...}`; v1 adds the code a client branches on."""

    response = await http.get("/api/runs/nope")
    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "not_found"
    assert body["error"]


async def test_an_unknown_workflow_cannot_be_submitted(
    http: httpx.AsyncClient,
) -> None:
    """404, and the code says which of the two 404s it is."""

    response = await http.post("/api/workflows/nope/runs", json={"title": "hi"})
    assert response.status_code == 404
    assert response.json()["code"] == "unknown_workflow"


async def test_a_submission_with_no_title_is_refused(
    http: httpx.AsyncClient,
) -> None:
    """v0's 400 "title is required" is v1's 422 on `body.title` (08)."""

    response = await http.post("/api/workflows/pipe/runs", json={})
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation"
    assert [error["loc"] for error in body["errors"]] == [["body", "title"]]


async def test_the_agent_api_refuses_the_wrong_task_token(
    http: httpx.AsyncClient,
) -> None:
    """A task token is the only credential the agent surface accepts.

    The run is left parked on its question, so there is a live attempt
    with a token to get wrong. Two refusals, and they are different
    refusals: no header at all is the missing parameter the endpoint
    declares, and a header that is not this task's token is the 403 the
    MVP answered with (12 §Tokens).
    """

    run_id = await submit(http, "asking", "who are you")
    pending = await until(
        lambda: _inbox(http, run_id), what="the question to reach the inbox"
    )
    task_id = pending[0]["task_id"]

    missing = await http.post(f"/api/agent/tasks/{task_id}/submit", json={"x": 1})
    assert missing.status_code == 422, missing.text
    assert missing.json()["errors"][0]["loc"] == ["header", "x-athanore-token"]

    wrong = await http.post(
        f"/api/agent/tasks/{task_id}/submit",
        json={"x": 1},
        headers={"X-Athanore-Token": "not-the-token"},
    )
    assert wrong.status_code == 403, wrong.text
    assert wrong.json()["code"] == "forbidden"

    # And the operator's own view of the task never carries the token
    # that would have worked (12 §Tokens).
    task = await http.get(f"/api/tasks/{task_id}")
    assert "token" not in task.json()

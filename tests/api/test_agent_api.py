"""``/api/agent/``: the surface a task token reaches, and nothing else (T045).

The endpoint halves of two MVP suites land here: `test_submissions.py` —
the 422 that carries the schema, the payload that is not stored, and the
next submission winning — and `test_ask.py` — the policy gate, the three
modes, and the long-poll that returns on the answer rather than on the
clamp.

The attempt is **claimed and registered**, not run. A task token is
minted at claim and is live only while the attempt is (12 §Task tokens),
and four of the five routes need the attempt's live
:class:`~athanore.engine.context.TaskContext` — the ``output_model`` a
submission is checked against, the ``ask_policy`` an ask is gated on, the
request port an ask opens through. The `attempt` fixture below does what
the runner does, in the order the runner does it, and stops there: no
scheduler, no dispatch loop, no body.

Two rules are enforced on every response in this module rather than in a
test that has to remember them:

- **no token, anywhere.** The `client` fixture walks every JSON body and
  fails on a `token` or `token_hash` key at any depth, as
  `test_runs_api.py` does for the operator routes. The token is what
  authenticates these calls, and it is the one thing they may never
  report back.
- **the credential is the header.** Every request in this suite carries
  `X-Athanore-Token` and no operator credential, because that is the only
  thing an agent has.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from typing import Any, Literal

import httpx
import pytest
from fastapi import FastAPI
from pydantic import BaseModel

from athanore.api.routers.agent import MAX_WAIT
from athanore.engine import Engine
from athanore.engine.context import TaskContext
from athanore.engine.pools import Pool
from athanore.engine.services import TaskRequests, TaskServices
from athanore.events.bus import EventBus
from athanore.requests.service import RequestService
from athanore.settings import AthanoreSettings
from athanore.store.rows import LogAuthor, LogKind, RequestSource, TaskStatus
from athanore.store.uow import Store
from athanore.workflow import Workflow

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


NODE = "review"
FLUSH_INTERVAL = 0.02


# --------------------------------------------------------------------------
# The application, with a request service behind it
# --------------------------------------------------------------------------


@pytest.fixture
def request_service(store: Store, bus: EventBus) -> RequestService:
    """The one request service a host builds beside its engine (T031)."""

    return RequestService(store, bus)


@pytest.fixture
def engine(
    settings: AthanoreSettings,
    store: Store,
    bus: EventBus,
    request_service: RequestService,
) -> Engine:
    """`tests/api/conftest.py`'s engine, wired to a request service.

    Overridden here because `/ask` and the long-poll are the two routes
    that need one: without it every attempt gets a port whose methods
    raise, which is what an engine that cannot ask anybody anything
    should do (04 §TaskContext).
    """

    engine = Engine(settings, store, bus, requests=request_service)
    engine.register(demo.finalize(), Pool("agent_pool", capacity=2))
    return engine


#: The two keys that may not appear in any response, at any depth.
FORBIDDEN = frozenset({"token", "token_hash"})


def keys(value: Any) -> Iterator[str]:
    """Every key anywhere in ``value``, however deeply nested."""

    if isinstance(value, dict):
        for key, item in value.items():  # pyright: ignore[reportUnknownVariableType]
            yield str(key)
            yield from keys(item)
    elif isinstance(value, list):
        for item in value:  # pyright: ignore[reportUnknownVariableType]
            yield from keys(item)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """The suite's client, with the no-token rule wired into it."""

    async def no_token_anywhere(response: httpx.Response) -> None:
        await response.aread()
        if "application/json" not in response.headers.get("content-type", ""):
            return
        leaked = sorted(FORBIDDEN.intersection(keys(response.json())))
        assert not leaked, f"{response.request.url} leaked {leaked}"

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        event_hooks={"response": [no_token_anywhere]},
    ) as http:
        yield http


# --------------------------------------------------------------------------
# One claimed, live attempt
# --------------------------------------------------------------------------


class Attempt:
    """A claimed attempt, its live context, and the header it is reached by."""

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
    """Claim a task and register its context, the way the runner does.

    Enqueue, claim (which mints the token and moves the row to
    ``in_progress``), build the services and the request port, attach the
    port to the context and register the context on ``engine.live``. That
    is the whole of what makes a token live and a submission acceptable;
    everything after it in the runner is the node body, which this suite
    has none of.
    """

    async def make(
        title: str = "ship it",
        description: str = "the brief",
        *,
        payload: Any = None,
        node: str = NODE,
    ) -> Attempt:
        async with store.uow() as uow:
            run = await uow.runs.insert("demo", title, description)
            task = await uow.tasks.enqueue(
                run.id, node, payload, priority=0, explicit=False
            )
            claimed = await uow.tasks.claim_ready(1, ["demo"])
        assert [one.task.id for one in claimed] == [task.id]
        port = TaskRequests(request_service, run_id=run.id, task_id=task.id)
        ctx = TaskContext(
            run_id=run.id,
            task_id=task.id,
            workflow="demo",
            node=node,
            attempt=task.attempt,
            token=claimed[0].token,
            api_base="http://127.0.0.1:4002",
            services=TaskServices(
                store,
                run_id=run.id,
                task_id=task.id,
                node=node,
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
# GET /api/agent/tasks/{id}
# --------------------------------------------------------------------------


async def test_the_task_read_carries_the_brief_the_payload_and_the_log(
    client: httpx.AsyncClient, attempt: Claim, store: Store
) -> None:
    """08 §Agent-facing, field for field."""

    live = await attempt("ship it", "review the branch", payload={"branch": "feat/x"})
    async with store.uow() as uow:
        await uow.log.append(
            run_id=live.run_id,
            node=NODE,
            author=LogAuthor.agent,
            text="the previous stage's deliverable",
            task_id=live.task_id,
        )
    response = await client.get(live.base, headers=live.headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["task_id"] == live.task_id
    assert body["run_id"] == live.run_id
    assert body["workflow"] == "demo"
    assert body["node"] == NODE
    assert body["attempt"] == 1
    assert body["title"] == "ship it"
    assert body["description"] == "review the branch"
    assert body["input"] == {"branch": "feat/x"}
    assert body["output_schema"] is None
    assert [entry["text"] for entry in body["log"]] == [
        "the previous stage's deliverable"
    ]


async def test_a_task_with_no_payload_reports_a_null_input(
    client: httpx.AsyncClient, attempt: Claim
) -> None:
    live = await attempt()
    body = (await client.get(live.base, headers=live.headers)).json()
    assert body["input"] is None
    assert body["log"] == []


async def test_the_agent_never_sees_the_stats_lines(
    client: httpx.AsyncClient, attempt: Claim, store: Store
) -> None:
    """D56: token counts and costs are operator information."""

    live = await attempt()
    async with store.uow() as uow:
        for text, kind in (
            ("engineering: built it", LogKind.deliverable),
            ("[stats] node=review model=fake/m1 in=10 out=5", LogKind.stats),
            ("attempt 1 failed: timeout", LogKind.failure),
            ("an operator note", None),
        ):
            await uow.log.append(
                run_id=live.run_id,
                node=NODE,
                author=LogAuthor.agent,
                text=text,
                task_id=live.task_id,
                kind=kind,
            )
    body = (await client.get(live.base, headers=live.headers)).json()
    assert [entry["text"] for entry in body["log"]] == [
        "engineering: built it",
        "attempt 1 failed: timeout",
        "an operator note",
    ]
    # The operator's own read of the same log keeps them.
    operator = (await client.get(f"/api/runs/{live.run_id}/log")).json()
    assert any(entry["text"].startswith("[stats]") for entry in operator)


async def test_the_declared_output_model_is_reported_as_a_json_schema(
    client: httpx.AsyncClient, attempt: Claim
) -> None:
    """What the `native` tier reads to build its `submit_result` tool (05)."""

    live = await attempt()
    live.ctx.output_model = Review
    body = (await client.get(live.base, headers=live.headers)).json()
    assert body["output_schema"] == Review.model_json_schema()
    assert "verdict" in body["output_schema"]["properties"]


# --------------------------------------------------------------------------
# The credential
# --------------------------------------------------------------------------


async def test_a_wrong_token_is_refused_on_every_route(
    client: httpx.AsyncClient, attempt: Claim
) -> None:
    live = await attempt()
    wrong = {"X-Athanore-Token": "not-the-token"}
    calls = [
        client.get(live.base, headers=wrong),
        client.post(f"{live.base}/log", json={"text": "x"}, headers=wrong),
        client.post(f"{live.base}/submit", json={"a": 1}, headers=wrong),
        client.post(f"{live.base}/ask", json={"prompt": "hi?"}, headers=wrong),
        client.get(f"{live.base}/requests/1", headers=wrong),
    ]
    for call in calls:
        response = await call
        assert response.status_code == 403, response.text
        assert response.json()["code"] == "forbidden"


async def test_a_token_of_another_task_reaches_nothing(
    client: httpx.AsyncClient, attempt: Claim
) -> None:
    """A token names one attempt; it cannot be pointed at another."""

    mine = await attempt()
    theirs = await attempt()
    response = await client.get(theirs.base, headers=mine.headers)
    assert response.status_code == 403


async def test_a_token_dies_with_the_attempt_it_was_minted_for(
    client: httpx.AsyncClient, attempt: Claim, store: Store
) -> None:
    """12 §Task tokens: valid only while `in_progress` or `waiting`."""

    live = await attempt()
    assert (await client.get(live.base, headers=live.headers)).status_code == 200
    async with store.uow() as uow:
        await uow.tasks.finish(live.task_id, TaskStatus.done.value, result=None)
    response = await client.post(
        f"{live.base}/submit", json={"late": True}, headers=live.headers
    )
    assert response.status_code == 403


async def test_a_waiting_attempt_is_still_the_tokens_own(
    client: httpx.AsyncClient, attempt: Claim, store: Store
) -> None:
    """A body parked on a request goes on writing once it is answered."""

    live = await attempt()
    async with store.uow() as uow:
        await uow.tasks.set_status(live.task_id, TaskStatus.waiting.value)
    assert (await client.get(live.base, headers=live.headers)).status_code == 200


async def test_a_missing_header_names_the_header(
    client: httpx.AsyncClient, attempt: Claim
) -> None:
    """Nothing was presented to refuse, so it is the 422 of 08 §Conventions."""

    live = await attempt()
    response = await client.get(live.base)
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation"
    located = [str(error["loc"]).lower() for error in body["errors"]]
    assert any("x-athanore-token" in one for one in located)


async def test_an_operator_credential_is_not_a_task_token(
    client: httpx.AsyncClient, attempt: Claim
) -> None:
    """Operator routes never accept a task token, and nor the reverse."""

    live = await attempt()
    response = await client.get(
        live.base, headers={"Authorization": f"Bearer {live.token}"}
    )
    assert response.status_code == 422  # the header the route requires is absent


# --------------------------------------------------------------------------
# POST /log
# --------------------------------------------------------------------------


async def test_a_log_entry_is_written_as_the_agent_under_its_node(
    client: httpx.AsyncClient, attempt: Claim, store: Store
) -> None:
    live = await attempt()
    response = await client.post(
        f"{live.base}/log", json={"text": "reviewed it: approve"}, headers=live.headers
    )
    assert response.status_code == 200, response.text
    log_id = response.json()["log_id"]
    async with store.reader() as reader:
        entries = await reader.log.list(live.run_id)
    written = [(one.id, one.author, one.node, one.task_id) for one in entries]
    assert written == [(log_id, LogAuthor.agent, NODE, live.task_id)]
    assert entries[0].text == "reviewed it: approve"


async def test_a_log_entry_announces_itself(
    client: httpx.AsyncClient, attempt: Claim, store: Store
) -> None:
    """`log.appended` is what re-renders the log in the SPA (10 §Realtime)."""

    live = await attempt()
    await client.post(
        f"{live.base}/log", json={"text": "the deliverable"}, headers=live.headers
    )
    async with store.reader() as reader:
        events = await reader.events.list_for_run(live.run_id)
    appended = [event for event in events if event.name == "log.appended"]
    assert len(appended) == 1
    assert appended[0].data["author"] == "agent"
    assert appended[0].data["preview"] == "the deliverable"


async def test_a_blank_log_entry_is_refused(
    client: httpx.AsyncClient, attempt: Claim
) -> None:
    live = await attempt()
    response = await client.post(
        f"{live.base}/log", json={"text": "   "}, headers=live.headers
    )
    assert response.status_code == 422
    assert response.json()["code"] == "validation"


async def test_the_agent_read_shows_what_the_agent_wrote(
    client: httpx.AsyncClient, attempt: Claim
) -> None:
    """The work log is the channel, so an agent reads its own entry back."""

    live = await attempt()
    await client.post(
        f"{live.base}/log", json={"text": "stage one done"}, headers=live.headers
    )
    body = (await client.get(live.base, headers=live.headers)).json()
    assert [entry["text"] for entry in body["log"]] == ["stage one done"]


# --------------------------------------------------------------------------
# POST /submit
# --------------------------------------------------------------------------


async def test_a_submission_with_no_model_declared_is_stored_raw(
    client: httpx.AsyncClient, attempt: Claim, store: Store
) -> None:
    live = await attempt()
    response = await client.post(
        f"{live.base}/submit", json={"anything": [1, 2]}, headers=live.headers
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"ok": True, "note": None}
    async with store.reader() as reader:
        row = await reader.submissions.latest(live.task_id)
    assert row is not None and row.payload == {"anything": [1, 2]}


async def test_a_scalar_is_a_submission_too(
    client: httpx.AsyncClient, attempt: Claim, store: Store
) -> None:
    """08: *any* JSON. The MVP's `submit "done"` still submits."""

    live = await attempt()
    response = await client.post(
        f"{live.base}/submit", json="done", headers=live.headers
    )
    assert response.status_code == 200, response.text
    async with store.reader() as reader:
        row = await reader.submissions.latest(live.task_id)
    assert row is not None and row.payload == "done"


async def test_a_fitting_submission_is_stored_and_announced(
    client: httpx.AsyncClient, attempt: Claim, store: Store
) -> None:
    live = await attempt()
    live.ctx.output_model = Review
    response = await client.post(
        f"{live.base}/submit",
        json={"verdict": "approve", "feedback": "ok"},
        headers=live.headers,
    )
    assert response.status_code == 200, response.text
    async with store.reader() as reader:
        row = await reader.submissions.latest(live.task_id)
        events = await reader.events.list_for_run(live.run_id)
    assert row is not None
    assert row.payload == {"verdict": "approve", "feedback": "ok"}
    names = [event.name for event in events]
    assert names.count("submission.accepted") == 1
    assert "submission.rejected" not in names


async def test_a_misfit_submission_is_422_with_the_errors_and_the_schema(
    client: httpx.AsyncClient, attempt: Claim, store: Store
) -> None:
    """The endpoint half of the MVP's `test_submissions.py`."""

    live = await attempt()
    live.ctx.output_model = Review
    response = await client.post(
        f"{live.base}/submit", json={"verdict": "maybe"}, headers=live.headers
    )
    assert response.status_code == 422, response.text
    body = response.json()
    assert body["error"] == "submission failed validation"
    assert body["code"] == "validation"
    assert body["errors"][0]["loc"] == ["verdict"]
    assert set(body["errors"][0]) == {"loc", "msg", "type"}
    assert body["schema"] == Review.model_json_schema()
    async with store.reader() as reader:
        assert await reader.submissions.latest(live.task_id) is None
        events = await reader.events.list_for_run(live.run_id)
    names = [event.name for event in events]
    assert names.count("submission.rejected") == 1
    assert "submission.accepted" not in names


async def test_a_rejection_leaves_the_repair_material_on_the_context(
    client: httpx.AsyncClient, attempt: Claim
) -> None:
    """What 19 §Repair turn quotes back, set here and read by T035 (D120)."""

    live = await attempt()
    live.ctx.output_model = Review
    await client.post(
        f"{live.base}/submit", json={"verdict": "maybe"}, headers=live.headers
    )
    rejection = live.ctx.last_rejection
    assert rejection is not None
    assert rejection["payload"] == {"verdict": "maybe"}
    assert rejection["errors"][0]["loc"] == ["verdict"]
    assert rejection["schema"]["title"] == "Review"


async def test_the_last_valid_submission_wins(
    client: httpx.AsyncClient, attempt: Claim, store: Store
) -> None:
    """D5, and the reason a repair turn is worth sending at all."""

    live = await attempt()
    live.ctx.output_model = Review
    first = await client.post(
        f"{live.base}/submit",
        json={"verdict": "changes_requested", "feedback": "no"},
        headers=live.headers,
    )
    misfit = await client.post(
        f"{live.base}/submit", json={"verdict": "maybe"}, headers=live.headers
    )
    second = await client.post(
        f"{live.base}/submit",
        json={"verdict": "approve", "feedback": "fixed"},
        headers=live.headers,
    )
    codes = (first.status_code, misfit.status_code, second.status_code)
    assert codes == (200, 422, 200)
    async with store.reader() as reader:
        latest = await reader.submissions.latest(live.task_id)
        rows = await reader.submissions.list(live.task_id)
    assert latest is not None
    assert latest.payload == {"verdict": "approve", "feedback": "fixed"}
    # The misfit is not among them: a rejected payload is not a submission.
    assert [row.payload["verdict"] for row in rows] == ["changes_requested", "approve"]


async def test_a_submission_to_an_attempt_this_server_is_not_running_is_409(
    client: httpx.AsyncClient, attempt: Claim, engine: Engine
) -> None:
    """No live context is exactly "the task is not in progress" (08)."""

    live = await attempt()
    engine.live.unregister(live.task_id)
    response = await client.post(
        f"{live.base}/submit", json={"verdict": "approve"}, headers=live.headers
    )
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "conflict"


async def test_log_and_ask_need_the_live_attempt_too(
    client: httpx.AsyncClient, attempt: Claim, engine: Engine
) -> None:
    """The read still works: it is the writes that need somewhere to land."""

    live = await attempt()
    engine.live.unregister(live.task_id)
    assert (await client.get(live.base, headers=live.headers)).status_code == 200
    logged = await client.post(
        f"{live.base}/log", json={"text": "orphan"}, headers=live.headers
    )
    asked = await client.post(
        f"{live.base}/ask", json={"prompt": "anyone?"}, headers=live.headers
    )
    assert (logged.status_code, asked.status_code) == (409, 409)


# --------------------------------------------------------------------------
# POST /ask
# --------------------------------------------------------------------------


async def test_ask_is_403_unless_the_policy_says_http(
    client: httpx.AsyncClient, attempt: Claim, store: Store
) -> None:
    """An agent cannot grant itself the right to interrupt a person."""

    live = await attempt()
    assert live.ctx.ask_policy == "off"
    response = await client.post(
        f"{live.base}/ask", json={"prompt": "which branch?"}, headers=live.headers
    )
    assert response.status_code == 403, response.text
    body = response.json()
    assert body["code"] == "forbidden"
    assert "ask_policy" in body["error"]
    async with store.reader() as reader:
        assert await reader.requests.list_views(live.run_id) == []


async def test_a_text_ask_opens_an_agent_question(
    client: httpx.AsyncClient, attempt: Claim, store: Store
) -> None:
    live = await attempt()
    live.ctx.ask_policy = "http"
    response = await client.post(
        f"{live.base}/ask", json={"prompt": "  which branch?  "}, headers=live.headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mode"] == "text"
    async with store.reader() as reader:
        [view] = await reader.requests.list_views(live.run_id)
    assert view.id == body["request_id"]
    assert view.task_id == live.task_id
    assert view.node == NODE
    assert view.prompt == "which branch?"
    assert view.source is RequestSource.agent
    assert view.kind == "question"
    assert view.pending is True


async def test_an_options_ask_carries_the_choices_it_offered(
    client: httpx.AsyncClient, attempt: Claim, store: Store
) -> None:
    live = await attempt()
    live.ctx.ask_policy = "http"
    response = await client.post(
        f"{live.base}/ask",
        json={
            "prompt": "ship?",
            "options": [
                "yes",
                {"option_id": "no", "name": "Not yet", "kind": "reject"},
            ],
        },
        headers=live.headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["mode"] == "options"
    async with store.reader() as reader:
        [view] = await reader.requests.list_views(live.run_id)
    assert view.options == [
        {"option_id": "yes", "name": "yes", "kind": None},
        {"option_id": "no", "name": "Not yet", "kind": "reject"},
    ]
    # And the service refuses an answer the question did not offer.
    refused = await client.post(
        f"/api/requests/{view.id}/answer", json={"option_id": "maybe"}
    )
    assert refused.status_code == 400
    assert refused.json()["code"] == "invalid_option"


async def test_a_form_ask_registers_the_schema_as_the_answers_validator(
    client: httpx.AsyncClient, attempt: Claim, store: Store
) -> None:
    """06 §Service: the answer is validated where it lands."""

    live = await attempt()
    live.ctx.ask_policy = "http"
    schema = {
        "type": "object",
        "properties": {"n": {"type": "integer"}},
        "required": ["n"],
    }
    response = await client.post(
        f"{live.base}/ask",
        json={"prompt": "how many?", "schema": schema},
        headers=live.headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["mode"] == "form"
    request_id = response.json()["request_id"]
    async with store.reader() as reader:
        view = await reader.requests.view(request_id)
    assert view is not None and view.schema_ == schema
    misfit = await client.post(
        f"/api/requests/{request_id}/answer", json={"value": {"n": "three"}}
    )
    assert misfit.status_code == 422
    assert misfit.json()["errors"][0]["loc"] == ["n"]
    accepted = await client.post(
        f"/api/requests/{request_id}/answer", json={"value": {"n": 3}}
    )
    assert accepted.status_code == 200


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({}, id="no prompt"),
        pytest.param({"prompt": "   "}, id="blank prompt"),
        pytest.param({"prompt": "x", "options": []}, id="no options"),
        pytest.param(
            {"prompt": "x", "options": ["a"], "schema": {"type": "object"}},
            id="both",
        ),
        pytest.param({"prompt": "x", "schema": "nope"}, id="schema is not an object"),
        pytest.param({"prompt": "x", "options": [{"name": "a"}]}, id="no option id"),
    ],
)
async def test_an_ill_formed_ask_is_refused_before_a_request_is_opened(
    client: httpx.AsyncClient, attempt: Claim, store: Store, body: dict[str, Any]
) -> None:
    live = await attempt()
    live.ctx.ask_policy = "http"
    response = await client.post(f"{live.base}/ask", json=body, headers=live.headers)
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "validation"
    async with store.reader() as reader:
        assert await reader.requests.list_views(live.run_id) == []


async def test_the_policy_is_checked_before_the_body(
    client: httpx.AsyncClient, attempt: Claim
) -> None:
    """A malformed ask is 422 whatever the policy is: the body is refused
    where every other body is, before the route function runs at all."""

    live = await attempt()
    response = await client.post(
        f"{live.base}/ask", json={"prompt": "x", "options": []}, headers=live.headers
    )
    assert response.status_code == 422


# --------------------------------------------------------------------------
# GET /requests/{rid}
# --------------------------------------------------------------------------


async def opened(client: httpx.AsyncClient, live: Attempt, **body: Any) -> int:
    """Open a question through `/ask` and return its request id."""

    live.ctx.ask_policy = "http"
    response = await client.post(
        f"{live.base}/ask",
        json={"prompt": "which branch?", **body},
        headers=live.headers,
    )
    assert response.status_code == 200, response.text
    request_id: int = response.json()["request_id"]
    return request_id


async def test_an_unanswered_request_polls_as_unanswered(
    client: httpx.AsyncClient, attempt: Claim
) -> None:
    live = await attempt()
    request_id = await opened(client, live)
    response = await client.get(
        f"{live.base}/requests/{request_id}", headers=live.headers
    )
    assert response.status_code == 200, response.text
    assert response.json() == {
        "request_id": request_id,
        "answered": False,
        "answer": None,
        "answered_by": None,
    }


async def test_the_long_poll_returns_when_the_answer_lands(
    client: httpx.AsyncClient, attempt: Claim
) -> None:
    """Not on the clamp: the wait ends the moment the answer is recorded."""

    live = await attempt()
    request_id = await opened(client, live)

    async def answer_later() -> None:
        await asyncio.sleep(0.05)
        response = await client.post(
            f"/api/requests/{request_id}/answer", json={"value": "main"}
        )
        assert response.status_code == 200, response.text

    started = time.monotonic()
    answering = asyncio.create_task(answer_later())
    polled = await client.get(
        f"{live.base}/requests/{request_id}",
        params={"wait": 30},
        headers=live.headers,
    )
    elapsed = time.monotonic() - started
    await answering
    assert polled.status_code == 200, polled.text
    assert polled.json() == {
        "request_id": request_id,
        "answered": True,
        "answer": "main",
        "answered_by": "user",
    }
    assert elapsed < 5


async def test_an_options_answer_polls_back_as_the_option_id(
    client: httpx.AsyncClient, attempt: Claim
) -> None:
    live = await attempt()
    request_id = await opened(client, live, options=["yes", "no"])
    await client.post(f"/api/requests/{request_id}/answer", json={"option_id": "no"})
    body = (
        await client.get(f"{live.base}/requests/{request_id}", headers=live.headers)
    ).json()
    assert body["answered"] is True
    assert body["answer"] == "no"


async def test_re_delivery_is_idempotent(
    client: httpx.AsyncClient, attempt: Claim
) -> None:
    """A dropped response costs nothing: the same answer comes back again."""

    live = await attempt()
    request_id = await opened(client, live)
    await client.post(f"/api/requests/{request_id}/answer", json={"value": "main"})
    url = f"{live.base}/requests/{request_id}"
    first = await client.get(url, headers=live.headers)
    second = await client.get(url, headers=live.headers)
    assert first.json() == second.json()
    assert second.json()["answer"] == "main"


async def test_a_request_of_another_task_is_not_readable(
    client: httpx.AsyncClient, attempt: Claim
) -> None:
    """A token names one attempt, so it polls only what that attempt asked."""

    mine = await attempt()
    theirs = await attempt()
    request_id = await opened(client, theirs)
    response = await client.get(
        f"{mine.base}/requests/{request_id}", headers=mine.headers
    )
    assert response.status_code == 404, response.text
    assert response.json()["code"] == "not_found"


async def test_an_unknown_request_is_a_404(
    client: httpx.AsyncClient, attempt: Claim
) -> None:
    live = await attempt()
    response = await client.get(f"{live.base}/requests/999", headers=live.headers)
    assert response.status_code == 404


async def test_the_wait_is_clamped_rather_than_refused(
    client: httpx.AsyncClient,
    attempt: Claim,
    request_service: RequestService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """19's loop asks for 60; an agent asking for an hour gets two minutes."""

    live = await attempt()
    request_id = await opened(client, live)
    waited: list[float] = []
    real = request_service.poll

    async def spy(rid: int, wait_s: float) -> Any:
        waited.append(wait_s)
        return await real(rid, 0.0)

    monkeypatch.setattr(request_service, "poll", spy)
    for asked in (0, 60, 100_000, -5):
        response = await client.get(
            f"{live.base}/requests/{request_id}",
            params={"wait": asked},
            headers=live.headers,
        )
        assert response.status_code == 200, response.text
    assert waited == [0.0, 60.0, MAX_WAIT, 0.0]

"""``/api/requests``: the inbox, one request, and every way an answer is
refused (T044b).

The MVP's `test_requests_api.py` lands here, extended by the two things
17 §T044b asks for by name: **every** answer error code, one test each,
and an inbox that excludes stale requests as well as answered ones.

Two things about the way this file is built are deliberate.

**The engine is composed with a request service.** `tests/api/conftest.py`
builds one without, because most of the API needs none; a request is the
one object that does, so this module overrides the fixture the way a host
composes the pair (06 §Service) — `athanore.requests` and
`athanore.engine` are independent siblings and neither builds the other.

**Requests are opened through the service, not written into the store.**
The refusals under test are the service's, and a row inserted behind its
back could be a row `create` would have refused (an `options` request
offering nothing, D115). What is written directly is only ever a *task's*
status, which is what makes a request stale.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from athanore.api.app import create_app
from athanore.engine import Engine
from athanore.engine.pools import Pool
from athanore.events.bus import EventBus
from athanore.graph import Graph
from athanore.requests.service import RequestService
from athanore.settings import AthanoreSettings
from athanore.store.rows import (
    AnswerAuthor,
    RequestKind,
    RequestMode,
    RequestRow,
    RequestSource,
    TaskStatus,
)
from athanore.store.uow import Store
from athanore.workflow import Workflow

# --------------------------------------------------------------------------
# The workflow, and an engine that can answer
# --------------------------------------------------------------------------

demo = Workflow("demo")


@demo.node(start=True)
async def plan(build: Any) -> None:
    """Ask a person something."""


@demo.node()
async def build() -> None:
    """Do the work."""


@pytest.fixture
def requests_service(store: Store, bus: EventBus) -> RequestService:
    """The one request service a host builds beside the engine."""

    return RequestService(store, bus)


@pytest.fixture
def engine(
    settings: AthanoreSettings,
    store: Store,
    bus: EventBus,
    requests_service: RequestService,
) -> Engine:
    """`tests/api/conftest.py`'s engine, composed with that service."""

    return Engine(settings, store, bus, requests=requests_service)


@pytest.fixture
def registered(engine: Engine) -> Graph:
    """The workflow, on a pool of its own."""

    graph = demo.finalize()
    engine.register(graph, Pool("requests_pool", capacity=4))
    return graph


# --------------------------------------------------------------------------
# Writing histories
# --------------------------------------------------------------------------


async def running_task(client: httpx.AsyncClient, store: Store) -> tuple[str, int]:
    """A run with its start task claimed: `(run_id, task_id)`."""

    response = await client.post(
        "/api/workflows/demo/runs", json={"title": "ship it", "description": ""}
    )
    assert response.status_code == 201, response.text
    run_id: str = response.json()["run_id"]
    async with store.uow() as uow:
        (claimed,) = await uow.tasks.claim_ready(1, ["demo"])
    return run_id, claimed.task.id


async def ask(
    service: RequestService,
    run_id: str,
    task_id: int,
    *,
    mode: RequestMode = RequestMode.text,
    prompt: str = "which way?",
    options: list[dict[str, Any]] | None = None,
    schema: dict[str, Any] | None = None,
    kind: RequestKind = RequestKind.question,
    source: RequestSource = RequestSource.node,
) -> RequestRow:
    """Open one request the way a node body's `human_input` does."""

    return await service.create(
        run_id,
        task_id,
        prompt,
        mode=mode,
        source=source,
        kind=kind,
        options=options,
        schema=schema,
    )


TWO_OPTIONS = [
    {"option_id": "allow", "name": "Allow", "kind": "allow_once"},
    {"option_id": "reject", "name": "Reject", "kind": "reject_once"},
]


async def end_task(store: Store, task_id: int) -> None:
    """Finish the attempt, which is what makes its requests stale."""

    async with store.uow() as uow:
        await uow.tasks.finish(task_id, TaskStatus.failed.value, error="died")


# --------------------------------------------------------------------------
# GET /api/requests — the inbox
# --------------------------------------------------------------------------


async def test_the_inbox_carries_08s_view_for_every_pending_request(
    client: httpx.AsyncClient,
    store: Store,
    requests_service: RequestService,
    registered: Graph,
) -> None:
    """`RequestView`, field for field (08 §Requests)."""

    run_id, task_id = await running_task(client, store)
    request = await ask(
        requests_service,
        run_id,
        task_id,
        mode=RequestMode.options,
        prompt="may I write the file?",
        options=TWO_OPTIONS,
        kind=RequestKind.permission,
        source=RequestSource.agent,
    )

    response = await client.get("/api/requests")

    assert response.status_code == 200
    (row,) = response.json()
    assert row["id"] == request.id
    assert row["run_id"] == run_id
    assert row["task_id"] == task_id
    assert row["node"] == "plan"
    assert row["prompt"] == "may I write the file?"
    assert row["mode"] == RequestMode.options.value
    assert row["source"] == RequestSource.agent.value
    assert row["kind"] == RequestKind.permission.value
    assert row["options"] == TWO_OPTIONS
    assert row["pending"] is True
    assert row["stale"] is False
    assert row["answer"] is None
    assert row["answered_by"] is None
    assert row["age"] >= 0
    assert set(row) == {
        "id",
        "run_id",
        "task_id",
        "node",
        "prompt",
        "mode",
        "source",
        "kind",
        "options",
        "schema",
        "tool_call",
        "pending",
        "stale",
        "answer",
        "answered_by",
        "created",
        "age",
    }


async def test_the_inbox_excludes_the_answered_and_the_stale(
    client: httpx.AsyncClient,
    store: Store,
    requests_service: RequestService,
    registered: Graph,
) -> None:
    """Pending is narrower than unanswered (06 §Restart durability).

    Three requests, one of each: one answered, one whose attempt has
    ended, and one still waiting. Only the last is in the inbox, and the
    stale one is the reason this is not "not answered".
    """

    run_id, task_id = await running_task(client, store)
    answered = await ask(requests_service, run_id, task_id, prompt="answered")
    await requests_service.answer(answered.id, value="yes")
    open_run, open_task = await running_task(client, store)
    waiting = await ask(requests_service, open_run, open_task, prompt="waiting")
    dead_run, dead_task = await running_task(client, store)
    stale = await ask(requests_service, dead_run, dead_task, prompt="stale")
    await end_task(store, dead_task)

    inbox = (await client.get("/api/requests")).json()
    everything = (await client.get("/api/requests?pending=false")).json()

    assert [row["id"] for row in inbox] == [waiting.id]
    assert [row["id"] for row in everything] == [answered.id, waiting.id, stale.id]
    by_id = {row["id"]: row for row in everything}
    assert by_id[stale.id]["stale"] is True
    assert by_id[stale.id]["pending"] is False
    assert by_id[answered.id]["stale"] is False


async def test_the_inbox_scopes_to_one_run(
    client: httpx.AsyncClient,
    store: Store,
    requests_service: RequestService,
    registered: Graph,
) -> None:
    """`?run=` filters; an id that names no run matches nothing."""

    first_run, first_task = await running_task(client, store)
    second_run, second_task = await running_task(client, store)
    mine = await ask(requests_service, first_run, first_task)
    await ask(requests_service, second_run, second_task)

    scoped = (await client.get("/api/requests", params={"run": first_run})).json()
    nowhere = (await client.get("/api/requests", params={"run": "nope"})).json()

    assert [row["id"] for row in scoped] == [mine.id]
    assert nowhere == []


async def test_an_empty_inbox_is_an_empty_list(
    client: httpx.AsyncClient, registered: Graph
) -> None:
    """Nothing to answer is `[]`, not a 404."""

    response = await client.get("/api/requests")

    assert response.status_code == 200
    assert response.json() == []


async def test_a_server_with_no_store_has_an_empty_inbox(
    settings: AthanoreSettings, engine: Engine
) -> None:
    """A store-less application holds no requests (04 §Shutdown)."""

    app = create_app(settings=settings, engine=engine, store=None)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as http:
        response = await http.get("/api/requests")

    assert response.status_code == 200
    assert response.json() == []


# --------------------------------------------------------------------------
# GET /api/requests/{id}
# --------------------------------------------------------------------------


async def test_one_request_reads_the_same_view_answered_or_not(
    client: httpx.AsyncClient,
    store: Store,
    requests_service: RequestService,
    registered: Graph,
) -> None:
    """The single read is the inbox's row, whatever its state."""

    run_id, task_id = await running_task(client, store)
    request = await ask(requests_service, run_id, task_id, prompt="text please")

    before = (await client.get(f"/api/requests/{request.id}")).json()
    await requests_service.answer(request.id, value="here it is")
    after = (await client.get(f"/api/requests/{request.id}")).json()

    assert before["pending"] is True and before["answer"] is None
    assert after["pending"] is False
    assert after["answer"] == "here it is"
    assert after["answered_by"] == AnswerAuthor.user.value


async def test_an_unknown_request_is_a_404_not_found(
    client: httpx.AsyncClient, registered: Graph
) -> None:
    """An id that names no request (06 §Errors)."""

    response = await client.get("/api/requests/999")

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


# --------------------------------------------------------------------------
# POST /api/requests/{id}/answer — the answer
# --------------------------------------------------------------------------


async def test_answering_an_options_request_returns_the_updated_view(
    client: httpx.AsyncClient,
    store: Store,
    requests_service: RequestService,
    registered: Graph,
) -> None:
    """The response is the request as it now is (08 §Requests)."""

    run_id, task_id = await running_task(client, store)
    request = await ask(
        requests_service,
        run_id,
        task_id,
        mode=RequestMode.options,
        options=TWO_OPTIONS,
        kind=RequestKind.permission,
    )

    response = await client.post(
        f"/api/requests/{request.id}/answer", json={"option_id": "allow"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == request.id
    assert body["answer"] == "allow"
    assert body["answered_by"] == AnswerAuthor.user.value
    assert body["pending"] is False
    assert body["stale"] is False
    assert (await client.get("/api/requests")).json() == []


async def test_answering_a_text_request_stores_the_string_as_given(
    client: httpx.AsyncClient,
    store: Store,
    requests_service: RequestService,
    registered: Graph,
) -> None:
    """The answer is the operator's, not the service's (06 §Errors)."""

    run_id, task_id = await running_task(client, store)
    request = await ask(requests_service, run_id, task_id)

    body = (
        await client.post(
            f"/api/requests/{request.id}/answer", json={"value": "  ship it  "}
        )
    ).json()

    assert body["answer"] == "  ship it  "


async def test_answering_a_form_request_stores_what_the_validator_returned(
    client: httpx.AsyncClient,
    store: Store,
    requests_service: RequestService,
    registered: Graph,
) -> None:
    """A `form` answer is an object, checked against the schema on the row."""

    run_id, task_id = await running_task(client, store)
    schema = {
        "type": "object",
        "properties": {"depth": {"type": "integer"}},
        "required": ["depth"],
    }
    request = await ask(
        requests_service,
        run_id,
        task_id,
        mode=RequestMode.form,
        schema=schema,
        kind=RequestKind.elicitation,
    )
    requests_service.register_schema_validator(request.id, schema)

    body = (
        await client.post(
            f"/api/requests/{request.id}/answer", json={"value": {"depth": 3}}
        )
    ).json()

    assert body["answer"] == {"depth": 3}
    assert body["schema"] == schema


# --------------------------------------------------------------------------
# ...and every way it is refused (06 §Errors, one test each)
# --------------------------------------------------------------------------


async def test_answering_an_unknown_request_is_a_404_not_found(
    client: httpx.AsyncClient, registered: Graph
) -> None:
    """`RequestNotFound`: the read every method makes first."""

    response = await client.post("/api/requests/999/answer", json={"value": "hi"})

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


async def test_a_second_answer_is_a_409_already_answered(
    client: httpx.AsyncClient,
    store: Store,
    requests_service: RequestService,
    registered: Graph,
) -> None:
    """One answer per request, claimed exactly once (06 §The model)."""

    run_id, task_id = await running_task(client, store)
    request = await ask(requests_service, run_id, task_id)
    first = await client.post(
        f"/api/requests/{request.id}/answer", json={"value": "yes"}
    )

    second = await client.post(
        f"/api/requests/{request.id}/answer", json={"value": "no"}
    )

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["code"] == "already_answered"
    assert (await client.get(f"/api/requests/{request.id}")).json()["answer"] == "yes"


async def test_answering_a_stale_request_is_a_409_stale_request(
    client: httpx.AsyncClient,
    store: Store,
    requests_service: RequestService,
    registered: Graph,
) -> None:
    """The attempt that asked is gone, so nothing would read the answer."""

    run_id, task_id = await running_task(client, store)
    request = await ask(requests_service, run_id, task_id)
    await end_task(store, task_id)

    response = await client.post(
        f"/api/requests/{request.id}/answer", json={"value": "too late"}
    )

    assert response.status_code == 409
    assert response.json()["code"] == "stale_request"


async def test_an_option_the_request_never_offered_is_a_400_invalid_option(
    client: httpx.AsyncClient,
    store: Store,
    requests_service: RequestService,
    registered: Graph,
) -> None:
    """`answer()` accepts only an `option_id` the request listed."""

    run_id, task_id = await running_task(client, store)
    request = await ask(
        requests_service,
        run_id,
        task_id,
        mode=RequestMode.options,
        options=TWO_OPTIONS,
        kind=RequestKind.permission,
    )

    response = await client.post(
        f"/api/requests/{request.id}/answer", json={"option_id": "maybe"}
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_option"
    assert (await client.get(f"/api/requests/{request.id}")).json()["pending"] is True


async def test_an_options_request_answered_with_a_value_is_an_invalid_option(
    client: httpx.AsyncClient,
    store: Store,
    requests_service: RequestService,
    registered: Graph,
) -> None:
    """The request's own `mode` decides which field is read (06 §Service)."""

    run_id, task_id = await running_task(client, store)
    request = await ask(
        requests_service,
        run_id,
        task_id,
        mode=RequestMode.options,
        options=TWO_OPTIONS,
    )

    response = await client.post(
        f"/api/requests/{request.id}/answer", json={"value": "allow"}
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_option"


async def test_a_text_request_answered_with_whitespace_is_a_422(
    client: httpx.AsyncClient,
    store: Store,
    requests_service: RequestService,
    registered: Graph,
) -> None:
    """`text`: a non-empty string, and whitespace alone is not one."""

    run_id, task_id = await running_task(client, store)
    request = await ask(requests_service, run_id, task_id)

    response = await client.post(
        f"/api/requests/{request.id}/answer", json={"value": "   "}
    )

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation"
    assert body["errors"] == []


async def test_a_form_answer_the_validator_refuses_is_a_422_with_its_errors(
    client: httpx.AsyncClient,
    store: Store,
    requests_service: RequestService,
    registered: Graph,
) -> None:
    """The per-field detail the SPA renders beside the offending input."""

    run_id, task_id = await running_task(client, store)
    schema = {
        "type": "object",
        "properties": {"depth": {"type": "integer"}},
        "required": ["depth"],
    }
    request = await ask(
        requests_service, run_id, task_id, mode=RequestMode.form, schema=schema
    )
    requests_service.register_schema_validator(request.id, schema)

    response = await client.post(
        f"/api/requests/{request.id}/answer", json={"value": {"depth": "deep"}}
    )

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation"
    assert [error["loc"] for error in body["errors"]] == [["depth"]]


async def test_a_form_request_answered_with_a_scalar_is_a_422(
    client: httpx.AsyncClient,
    store: Store,
    requests_service: RequestService,
    registered: Graph,
) -> None:
    """`form`: the answer must be an object before any validator sees it."""

    run_id, task_id = await running_task(client, store)
    request = await ask(requests_service, run_id, task_id, mode=RequestMode.form)

    response = await client.post(
        f"/api/requests/{request.id}/answer", json={"value": 3}
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation"


async def test_a_server_with_no_request_service_has_no_request_to_answer(
    settings: AthanoreSettings, store: Store, bus: EventBus
) -> None:
    """An engine composed without one never opened a request (04 §TaskContext)."""

    app: FastAPI = create_app(
        settings=settings, engine=Engine(settings, store, bus), store=store
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as http:
        response = await http.post("/api/requests/1/answer", json={"value": "hi"})

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"

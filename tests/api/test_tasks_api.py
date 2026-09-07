"""``/api/tasks``: the detail, the transcript, and the three verbs (T044b).

The MVP's `test_task_api.py` and the API half of its `test_management.py`
land here, beside the four things 17 §T044b asks for by name: the
transcript's `?after`/`?limit` pagination, the `live` flag, the
retry/move/status transitions, and the 409 a move into a join gets.

Built the way `test_runs_api.py` is, and for the same reason: the engine
is registered on but never started, so a history the assertions depend on
is **written** rather than produced. The suite's subject is the wire, and
the engine's own suites are where the same transitions are driven by the
dispatch loop.

The no-token rule is enforced on every response of every test in this
module by the `client` fixture below, exactly as it is in
`test_runs_api.py`: a task token is header-only (12 §Task tokens), and
`/api/tasks/{id}` is the operator route the MVP overloaded by credential,
so it is the one where the rule most needs proving.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from athanore.engine import Engine
from athanore.engine.pools import Pool
from athanore.graph import Graph
from athanore.store.rows import ChunkKind, TaskRow, TaskStatus
from athanore.store.uow import Store
from athanore.workflow import Workflow

# --------------------------------------------------------------------------
# The workflow under test
# --------------------------------------------------------------------------

demo = Workflow("demo")


@demo.node(start=True)
async def plan(split: Any) -> None:
    """Decide what to build."""


@demo.node()
async def split(work: Any) -> None:
    """Fan out."""


@demo.node()
async def work(gather: Any) -> None:
    """One branch."""


@demo.node(join=True)
async def gather(*, results: Any) -> None:
    """Close the fan-out."""


@pytest.fixture
def registered(engine: Engine) -> Graph:
    """The workflow, on a pool of its own."""

    graph = demo.finalize()
    engine.register(graph, Pool("tasks_pool", capacity=4))
    return graph


# --------------------------------------------------------------------------
# The client, and the rule it enforces on every response
# --------------------------------------------------------------------------

#: The two keys that must never appear in an operator response, at any
#: depth (12 §Task tokens).
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
# Writing histories
# --------------------------------------------------------------------------


async def submit(client: httpx.AsyncClient, title: str = "ship it") -> str:
    """Queue a run through the API and return its id."""

    response = await client.post(
        "/api/workflows/demo/runs", json={"title": title, "description": ""}
    )
    assert response.status_code == 201, response.text
    run_id: str = response.json()["run_id"]
    return run_id


async def start_task(client: httpx.AsyncClient, store: Store) -> TaskRow:
    """A run, with its start task claimed and in progress."""

    await submit(client)
    async with store.uow() as uow:
        (claimed,) = await uow.tasks.claim_ready(1, ["demo"])
    return claimed.task


async def finished(
    store: Store,
    task_id: int,
    status: TaskStatus,
    *,
    result: Any = None,
    error: str | None = None,
) -> TaskRow:
    """Put a claimed task in a terminal status."""

    async with store.uow() as uow:
        row = await uow.tasks.finish(
            task_id, status.value, result=result, error=error, terminal=False
        )
    assert row is not None
    return row


async def status_of(store: Store, task_id: int) -> TaskStatus:
    """The stored status of one task."""

    async with store.reader() as reader:
        row = await reader.tasks.get(task_id)
    assert row is not None
    return row.status


async def transcript(
    store: Store, task_id: int, count: int, kind: ChunkKind = ChunkKind.text
) -> None:
    """``count`` chunks, numbered from 1, on one task."""

    async with store.uow() as uow:
        await uow.stream.append_batch(
            task_id, [(seq, kind.value, f"chunk {seq}") for seq in range(1, count + 1)]
        )


# --------------------------------------------------------------------------
# GET /api/tasks/{id}
# --------------------------------------------------------------------------


async def test_the_detail_is_08s_task_row_with_its_submissions(
    client: httpx.AsyncClient, store: Store, registered: Graph
) -> None:
    """`TaskDetail`, field for field (08 §Tasks)."""

    task = await start_task(client, store)
    async with store.uow() as uow:
        await uow.submissions.insert(task.id, {"first": True})
        await uow.submissions.insert(task.id, {"second": True})

    response = await client.get(f"/api/tasks/{task.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == task.id
    assert body["run_id"] == task.run_id
    assert body["node"] == "plan"
    assert body["attempt"] == 1
    assert body["status"] == TaskStatus.in_progress.value
    assert body["terminal"] is False
    assert body["branch"] == []
    assert [one["payload"] for one in body["submissions"]] == [
        {"first": True},
        {"second": True},
    ]
    assert set(body) == {
        "id",
        "run_id",
        "node",
        "attempt",
        "status",
        "payload",
        "result",
        "error",
        "priority",
        "explicit",
        "stats",
        "lineage",
        "terminal",
        "branch",
        "created",
        "started",
        "finished",
        "submissions",
    }


async def test_a_claimed_attempt_has_a_token_hash_the_detail_never_shows(
    client: httpx.AsyncClient, store: Store, registered: Graph
) -> None:
    """The walk on every response has something to find, and finds nothing.

    The claim mints a token and stores its SHA-256 (04 §Dispatch), so the
    row behind this response *does* carry one — and the operator view has
    no field that could report it (12 §Task tokens).
    """

    task = await start_task(client, store)
    async with store.reader() as reader:
        stored = await reader.tasks.get(task.id)
    assert stored is not None and stored.token_hash is not None

    body = (await client.get(f"/api/tasks/{task.id}")).json()

    assert not FORBIDDEN.intersection(keys(body))


async def test_a_task_with_no_submissions_reports_an_empty_list(
    client: httpx.AsyncClient, store: Store, registered: Graph
) -> None:
    """Nothing submitted is `[]`, never an omitted field."""

    task = await start_task(client, store)

    body = (await client.get(f"/api/tasks/{task.id}")).json()

    assert body["submissions"] == []


async def test_an_unknown_task_is_a_404_not_found(
    client: httpx.AsyncClient, registered: Graph
) -> None:
    """An id that names no attempt (08 §Conventions)."""

    response = await client.get("/api/tasks/999")

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


async def test_a_server_with_no_store_holds_no_tasks(
    settings: Any, engine: Engine
) -> None:
    """A store-less application answers 404 rather than 500 (04 §Shutdown)."""

    from athanore.api.app import create_app

    app = create_app(settings=settings, engine=engine, store=None)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as http:
        response = await http.get("/api/tasks/1")

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


# --------------------------------------------------------------------------
# GET /api/tasks/{id}/stream
# --------------------------------------------------------------------------


async def test_the_stream_returns_the_whole_transcript_by_default(
    client: httpx.AsyncClient, store: Store, registered: Graph
) -> None:
    """`?after=0` is the transcript from the start (08 §Tasks)."""

    task = await start_task(client, store)
    await transcript(store, task.id, 3)

    body = (await client.get(f"/api/tasks/{task.id}/stream")).json()

    assert [chunk["seq"] for chunk in body["chunks"]] == [1, 2, 3]
    assert [chunk["text"] for chunk in body["chunks"]] == [
        "chunk 1",
        "chunk 2",
        "chunk 3",
    ]
    assert set(body["chunks"][0]) == {"seq", "kind", "text", "created"}
    assert body["chunks"][0]["kind"] == ChunkKind.text.value
    assert body["last_seq"] == 3


async def test_the_stream_pages_by_after_and_limit(
    client: httpx.AsyncClient, store: Store, registered: Graph
) -> None:
    """The cursor is `seq`, and `last_seq` is the highest **stored**.

    A client that has read two of five chunks is told the transcript
    reaches 5, which is how it knows it is behind without asking again.
    """

    task = await start_task(client, store)
    await transcript(store, task.id, 5)

    first = (
        await client.get(f"/api/tasks/{task.id}/stream", params={"limit": 2})
    ).json()
    second = (
        await client.get(
            f"/api/tasks/{task.id}/stream", params={"after": 2, "limit": 2}
        )
    ).json()
    last = (
        await client.get(f"/api/tasks/{task.id}/stream", params={"after": 4})
    ).json()

    assert [chunk["seq"] for chunk in first["chunks"]] == [1, 2]
    assert [chunk["seq"] for chunk in second["chunks"]] == [3, 4]
    assert [chunk["seq"] for chunk in last["chunks"]] == [5]
    assert first["last_seq"] == second["last_seq"] == last["last_seq"] == 5


async def test_a_caught_up_reader_gets_an_empty_page_and_the_same_last_seq(
    client: httpx.AsyncClient, store: Store, registered: Graph
) -> None:
    """Nothing new is `[]`, not a 404 and not a repeat of the last chunk."""

    task = await start_task(client, store)
    await transcript(store, task.id, 2)

    body = (await client.get(f"/api/tasks/{task.id}/stream?after=2")).json()

    assert body["chunks"] == []
    assert body["last_seq"] == 2


async def test_a_task_that_never_streamed_reports_last_seq_zero(
    client: httpx.AsyncClient, store: Store, registered: Graph
) -> None:
    """No transcript is an empty one, and `0` is "nothing stored"."""

    task = await start_task(client, store)

    body = (await client.get(f"/api/tasks/{task.id}/stream")).json()

    assert body == {"chunks": [], "last_seq": 0, "live": True}


@pytest.mark.parametrize(
    ("status", "live"),
    [
        (TaskStatus.in_progress, True),
        (TaskStatus.waiting, True),
        (TaskStatus.done, False),
        (TaskStatus.failed, False),
        (TaskStatus.cancelled, False),
        (TaskStatus.dead_letter, False),
    ],
)
async def test_live_is_the_attempt_still_running(
    client: httpx.AsyncClient,
    store: Store,
    registered: Graph,
    status: TaskStatus,
    live: bool,
) -> None:
    """`live` covers `waiting` as well as `in_progress`.

    A waiting attempt is parked on a request nobody has answered yet, and
    answering it is what makes the agent go on writing — the docked
    request panel sits under that very transcript (10 §Panes) — so a
    `live` that excluded `waiting` would stop the SPA polling at the one
    moment the stream is about to grow again.
    """

    task = await start_task(client, store)
    if status is not TaskStatus.in_progress:
        async with store.uow() as uow:
            if status is TaskStatus.waiting:
                await uow.tasks.set_status(task.id, status.value)
            else:
                await uow.tasks.finish(task.id, status.value)

    body = (await client.get(f"/api/tasks/{task.id}/stream")).json()

    assert body["live"] is live


async def test_a_ready_task_has_no_live_transcript(
    client: httpx.AsyncClient, store: Store, registered: Graph
) -> None:
    """Queued is not running: nothing is writing to it yet."""

    run_id = await submit(client)
    async with store.reader() as reader:
        (task,) = await reader.tasks.list_for_run(run_id)

    body = (await client.get(f"/api/tasks/{task.id}/stream")).json()

    assert task.status is TaskStatus.ready
    assert body["live"] is False


async def test_the_stream_of_an_unknown_task_is_a_404(
    client: httpx.AsyncClient, registered: Graph
) -> None:
    """The transcript of nothing is not an empty transcript."""

    response = await client.get("/api/tasks/999/stream")

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 5001}, {"after": -1}])
async def test_the_stream_refuses_a_cursor_outside_its_bounds(
    client: httpx.AsyncClient, store: Store, registered: Graph, params: dict[str, int]
) -> None:
    """`?after` and `?limit` are bounded, so a typo is a 422."""

    task = await start_task(client, store)

    response = await client.get(f"/api/tasks/{task.id}/stream", params=params)

    assert response.status_code == 422
    assert response.json()["code"] == "validation"


# --------------------------------------------------------------------------
# POST /api/tasks/{id}/retry
# --------------------------------------------------------------------------


async def test_retry_queues_the_next_attempt_of_a_stopped_task(
    client: httpx.AsyncClient, store: Store, registered: Graph
) -> None:
    """Same node, same payload, next attempt number (`Ops.retry`)."""

    task = await start_task(client, store)
    await finished(store, task.id, TaskStatus.failed, error="boom")

    response = await client.post(f"/api/tasks/{task.id}/retry")

    assert response.status_code == 200
    retry_id = response.json()["task_id"]
    assert response.json() == {"task_id": retry_id}
    detail = (await client.get(f"/api/tasks/{retry_id}")).json()
    assert detail["node"] == "plan"
    assert detail["attempt"] == 2
    assert detail["status"] == TaskStatus.ready.value
    assert detail["lineage"] == {"from": task.id, "reason": "manual_retry"}


async def test_retry_keeps_the_failed_attempts_place_in_the_queue(
    client: httpx.AsyncClient, store: Store, registered: Graph
) -> None:
    """`created` travels with a retry; `created DESC` is the last tiebreak."""

    task = await start_task(client, store)
    await finished(store, task.id, TaskStatus.failed, error="boom")

    retry_id = (await client.post(f"/api/tasks/{task.id}/retry")).json()["task_id"]

    detail = (await client.get(f"/api/tasks/{retry_id}")).json()
    original = (await client.get(f"/api/tasks/{task.id}")).json()
    assert detail["created"] == original["created"]


async def test_retry_of_a_running_task_is_a_409_conflict(
    client: httpx.AsyncClient, store: Store, registered: Graph
) -> None:
    """A second attempt of a task that has one is two attempts of one task."""

    task = await start_task(client, store)

    response = await client.post(f"/api/tasks/{task.id}/retry")

    assert response.status_code == 409
    assert response.json()["code"] == "conflict"


async def test_retry_of_an_unknown_task_is_a_404(
    client: httpx.AsyncClient, registered: Graph
) -> None:
    """The verb resolves its task before it does anything."""

    response = await client.post("/api/tasks/999/retry")

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


# --------------------------------------------------------------------------
# POST /api/tasks/{id}/move
# --------------------------------------------------------------------------


async def test_move_cancels_the_attempt_and_enqueues_its_work_elsewhere(
    client: httpx.AsyncClient, store: Store, registered: Graph
) -> None:
    """The payload travels, the old row is cancelled (`Ops.move`)."""

    task = await start_task(client, store)

    response = await client.post(f"/api/tasks/{task.id}/move", json={"node": "work"})

    assert response.status_code == 200
    moved_id = response.json()["task_id"]
    moved = (await client.get(f"/api/tasks/{moved_id}")).json()
    assert moved["node"] == "work"
    assert moved["status"] == TaskStatus.ready.value
    assert moved["lineage"] == {"from": task.id, "reason": "move"}
    assert await status_of(store, task.id) is TaskStatus.cancelled


async def test_move_into_a_join_is_a_409_conflict(
    client: httpx.AsyncClient, store: Store, registered: Graph
) -> None:
    """T044b's rule, surfaced: a join is dispatched by its arrivals (04 §Fan-in).

    A task moved into one would be a join attempt carrying a single
    branch's payload, with no arrival recorded — a run that then waits
    forever for branches that already landed.
    """

    task = await start_task(client, store)

    response = await client.post(f"/api/tasks/{task.id}/move", json={"node": "gather"})

    assert response.status_code == 409
    assert response.json()["code"] == "conflict"
    assert await status_of(store, task.id) is TaskStatus.in_progress


async def test_move_to_a_node_the_workflow_does_not_declare_is_a_404(
    client: httpx.AsyncClient, store: Store, registered: Graph
) -> None:
    """`unknown_node`, its own code under the same 404 (08 §Conventions)."""

    task = await start_task(client, store)

    response = await client.post(f"/api/tasks/{task.id}/move", json={"node": "nowhere"})

    assert response.status_code == 404
    assert response.json()["code"] == "unknown_node"


async def test_move_refuses_a_blank_node_before_the_engine_is_reached(
    client: httpx.AsyncClient, store: Store, registered: Graph
) -> None:
    """The body model strips and requires a name (08 §Conventions)."""

    task = await start_task(client, store)

    response = await client.post(f"/api/tasks/{task.id}/move", json={"node": "   "})

    assert response.status_code == 422
    assert response.json()["code"] == "validation"


# --------------------------------------------------------------------------
# POST /api/tasks/{id}/status
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status", [TaskStatus.ready, TaskStatus.cancelled, TaskStatus.dead_letter]
)
async def test_status_writes_the_three_an_operator_may_set(
    client: httpx.AsyncClient, store: Store, registered: Graph, status: TaskStatus
) -> None:
    """The transitions of 08 §Tasks, from an attempt in progress."""

    task = await start_task(client, store)

    response = await client.post(
        f"/api/tasks/{task.id}/status", json={"status": status.value}
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "note": None}
    assert await status_of(store, task.id) is status


async def test_status_ready_re_opens_a_run_that_had_ended(
    client: httpx.AsyncClient, store: Store, registered: Graph
) -> None:
    """`ready` re-dispatches, so the run it belongs to is running again."""

    task = await start_task(client, store)
    await finished(store, task.id, TaskStatus.dead_letter, error="gave up")
    async with store.uow() as uow:
        await uow.runs.set_status(task.run_id, "failed")

    response = await client.post(
        f"/api/tasks/{task.id}/status", json={"status": "ready"}
    )

    assert response.status_code == 200
    run = (await client.get(f"/api/runs/{task.run_id}")).json()
    assert run["status"] == "running"


@pytest.mark.parametrize("status", ["done", "in_progress", "sleeping"])
async def test_status_refuses_anything_but_the_three(
    client: httpx.AsyncClient, store: Store, registered: Graph, status: str
) -> None:
    """The other four are the engine's own record, not an operator's to write."""

    task = await start_task(client, store)

    response = await client.post(
        f"/api/tasks/{task.id}/status", json={"status": status}
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation"
    assert await status_of(store, task.id) is TaskStatus.in_progress


async def test_status_of_an_unknown_task_is_a_404(
    client: httpx.AsyncClient, registered: Graph
) -> None:
    """The verb resolves its task before it writes anything."""

    response = await client.post("/api/tasks/999/status", json={"status": "cancelled"})

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"

"""``/api/runs``: the operator verbs, the reads, and the graph (T044a).

The HTTP halves of five of the MVP's suites land here — `test_edit_run.py`,
and the API halves of `test_management.py`, `test_pause.py`,
`test_run_log.py` and `test_priority.py` — beside the four things 17
§T044a asks for by name: the `state` precedence on a run with a retry
pending, a fan-out that reports its branches, a join that reports `2 of
3`, and `position {index}` clamping at both ends.

Two things about the way this file is built are deliberate.

**The state is written, not run.** The subject is the projection 08
§Graph semantics specifies, so the histories it projects — a failed
attempt with a retry queued, three branches of which two arrived, a run
with two terminal outputs — are written straight into the store. The
engine's own suites are where those histories are *produced*; here they
are the input, and an input a test can state exactly is one that cannot
flake.

**No response in this suite may contain a token.** The `client` fixture
below walks every JSON body every request in this module returns and
fails on a `token` or a `token_hash` key at any depth. A task token is
header-only and appears in no operator response (12 §Task tokens); the
walk is what makes that structural rather than a spot check, and
`test_a_claimed_attempt_has_a_token_hash_the_wire_never_shows` proves the
walk has something to find.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator, Sequence
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from athanore.engine import Engine
from athanore.engine.pools import Pool
from athanore.events.model import Event
from athanore.events.names import EventName
from athanore.graph import Graph
from athanore.store.clock import now
from athanore.store.rows import BranchFrame, RunStatus, TaskRow, TaskStatus
from athanore.store.uow import Store
from athanore.workflow import Workflow

# --------------------------------------------------------------------------
# The workflows under test
# --------------------------------------------------------------------------

demo = Workflow("demo")


@demo.node(start=True)
async def plan(build: Any) -> None:
    """Decide what to build."""


@demo.node()
async def build(review: Any) -> None:
    """Do the work."""


@demo.node()
async def review(build: Any) -> None:
    """Send it back round."""


fanout = Workflow("fanout")


@fanout.node(start=True)
async def split(work: Any) -> None:
    """Fan out."""


@fanout.node()
async def work(gather: Any) -> None:
    """One branch."""


@fanout.node(join=True)
async def gather(*, results: Any) -> None:
    """Close the fan-out."""


@pytest.fixture
def registered(engine: Engine) -> dict[str, Graph]:
    """Both workflows, on one pool."""

    pool = Pool("runs_pool", capacity=4)
    graphs = {name: wf.finalize() for name, wf in (("demo", demo), ("fanout", fanout))}
    for graph in graphs.values():
        engine.register(graph, pool)
    return graphs


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
    """The suite's client, with the no-token rule wired into it.

    Overrides `tests/api/conftest.py`'s so that the check runs on every
    response of every test in this module rather than in one test that
    has to remember to call it.
    """

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


async def submit(
    client: httpx.AsyncClient,
    workflow: str = "demo",
    title: str = "ship it",
    description: str = "",
) -> str:
    """Queue a run through the API and return its id."""

    response = await client.post(
        f"/api/workflows/{workflow}/runs",
        json={"title": title, "description": description},
    )
    assert response.status_code == 201, response.text
    run_id: str = response.json()["run_id"]
    return run_id


async def task_at(
    store: Store,
    run_id: str,
    node: str,
    *,
    status: TaskStatus = TaskStatus.ready,
    attempt: int = 1,
    branch: Sequence[BranchFrame] = (),
    lineage: dict[str, Any] | None = None,
    result: Any = None,
    error: str | None = None,
    terminal: bool = False,
) -> TaskRow:
    """One attempt of ``node``, written straight into the store."""

    async with store.uow() as uow:
        row = await uow.tasks.enqueue(
            run_id,
            node,
            None,
            0,
            False,
            attempt=attempt,
            lineage=lineage,
            branch=branch,
        )
        if status is TaskStatus.ready:
            return row
        if status in (TaskStatus.in_progress, TaskStatus.waiting):
            moved = await uow.tasks.set_status(row.id, status.value)
        else:
            moved = await uow.tasks.finish(
                row.id, status.value, result=result, error=error, terminal=terminal
            )
        assert moved is not None
        return moved


async def emit(
    store: Store, run_id: str, task_id: int | None, name: EventName, **data: Any
) -> None:
    """Store one event without publishing it."""

    async with store.uow() as uow:
        await uow.events.insert_many(
            [
                Event(
                    run_id=run_id,
                    task_id=task_id,
                    name=name.value,
                    data=data,
                    created=now(),
                )
            ]
        )


async def transitioned(
    store: Store, run_id: str, from_task: int, to_node: str, times: int = 1
) -> None:
    """Record ``times`` crossings of the edge into ``to_node``."""

    for _ in range(times):
        await emit(
            store,
            run_id,
            None,
            EventName.task_enqueued,
            node=to_node,
            attempt=1,
            reason="transition",
            from_task=from_task,
            payload_present=False,
            branch=[],
        )


async def positions(client: httpx.AsyncClient) -> list[tuple[str, int]]:
    """The run list as ``(id, position)`` pairs, in list order."""

    body = (await client.get("/api/runs")).json()
    return [(row["id"], row["position"]) for row in body]


# --------------------------------------------------------------------------
# The list
# --------------------------------------------------------------------------


async def test_the_list_carries_08s_row_for_every_run(
    client: httpx.AsyncClient, registered: dict[str, Graph]
) -> None:
    """`RunSummary`, field for field (08 §Runs)."""

    run_id = await submit(client, title="the first")

    response = await client.get("/api/runs")

    assert response.status_code == 200
    (row,) = response.json()
    assert row["id"] == run_id
    assert row["workflow"] == "demo"
    assert row["title"] == "the first"
    assert row["status"] == RunStatus.queued.value
    assert row["position"] == 1
    assert row["current_nodes"] == []
    assert row["pending_requests"] == 0
    assert row["unregistered"] is False
    assert set(row) == {
        "id",
        "workflow",
        "title",
        "status",
        "position",
        "current_nodes",
        "pending_requests",
        "created",
        "updated",
        "unregistered",
    }


async def test_the_list_filters_by_status_and_by_workflow(
    client: httpx.AsyncClient, registered: dict[str, Graph]
) -> None:
    """The two query parameters of 08 §Runs."""

    queued = await submit(client, title="queued")
    paused = await submit(client, title="paused")
    other = await submit(client, "fanout", title="elsewhere")
    assert (await client.post(f"/api/runs/{paused}/pause")).status_code == 200

    by_status = (await client.get("/api/runs", params={"status": "paused"})).json()
    by_workflow = (await client.get("/api/runs", params={"workflow": "fanout"})).json()

    assert [row["id"] for row in by_status] == [paused]
    assert [row["id"] for row in by_workflow] == [other]
    assert {row["id"] for row in (await client.get("/api/runs")).json()} == {
        queued,
        paused,
        other,
    }


async def test_an_unknown_status_is_a_422_rather_than_an_empty_list(
    client: httpx.AsyncClient, registered: dict[str, Graph]
) -> None:
    """`?status=` is the run state machine, so a typo is refused."""

    response = await client.get("/api/runs", params={"status": "sleeping"})

    assert response.status_code == 422
    assert response.json()["code"] == "validation"


async def test_a_run_of_a_workflow_this_server_lacks_is_flagged_unregistered(
    client: httpx.AsyncClient, store: Store, registered: dict[str, Graph]
) -> None:
    """The field is not stored: it is what *this* server can run (03 §Run)."""

    async with store.uow() as uow:
        orphan = await uow.runs.insert("ghost", "left behind")

    listed = (await client.get("/api/runs")).json()

    assert {row["id"]: row["unregistered"] for row in listed}[orphan.id] is True


async def test_a_server_with_no_store_lists_no_runs() -> None:
    """`create_app()` with no collaborators runs nothing and holds nothing."""

    from athanore.api.app import create_app

    app = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as bare:
        listed = await bare.get("/api/runs")
        one = await bare.get("/api/runs/01JNOPE")

    assert listed.status_code == 200
    assert listed.json() == []
    assert one.status_code == 404
    assert one.json()["code"] == "not_found"


# --------------------------------------------------------------------------
# The detail
# --------------------------------------------------------------------------


async def test_the_detail_adds_the_description_the_tasks_and_the_totals(
    client: httpx.AsyncClient, store: Store, registered: dict[str, Graph]
) -> None:
    """`RunDetail` = the summary plus what the overview pane draws."""

    run_id = await submit(client, description="the long version")
    (start,) = await store_tasks(store, run_id)
    async with store.uow() as uow:
        await uow.tasks.set_stats(start.id, {"total_tokens": 120, "cost": 0.25})

    body = (await client.get(f"/api/runs/{run_id}")).json()

    assert body["description"] == "the long version"
    assert [task["node"] for task in body["tasks"]] == ["plan"]
    assert body["stats"]["total_tokens"] == 120
    assert body["stats"]["cost"] == pytest.approx(0.25)
    # Nothing is zero-filled: no attempt reported a duration (01 §Real data).
    assert body["stats"]["duration_s"] is None


async def store_tasks(store: Store, run_id: str) -> list[TaskRow]:
    """Every attempt of a run, oldest first."""

    async with store.reader() as reader:
        return await reader.tasks.list_for_run(run_id)


async def test_the_detail_reports_the_in_flight_nodes_and_the_pending_requests(
    client: httpx.AsyncClient, store: Store, registered: dict[str, Graph]
) -> None:
    """The list's two derived fields, recomputed for one run."""

    run_id = await submit(client)
    waiting = await task_at(store, run_id, "build", status=TaskStatus.waiting)
    await task_at(store, run_id, "review", status=TaskStatus.done)
    async with store.uow() as uow:
        await uow.requests.create(
            run_id,
            waiting.id,
            "which one?",
            mode="text",
            source="node",
            kind="question",
        )

    body = (await client.get(f"/api/runs/{run_id}")).json()

    assert body["current_nodes"] == ["build"]
    assert body["pending_requests"] == 1


async def test_outputs_carry_one_entry_per_terminal_attempt_with_its_branch(
    client: httpx.AsyncClient, store: Store, registered: dict[str, Graph]
) -> None:
    """D58: `outputs` is always a list, one entry per terminal task."""

    run_id = await submit(client, "fanout")
    fan = (await store_tasks(store, run_id))[0]
    first = await task_at(
        store,
        run_id,
        "work",
        status=TaskStatus.done,
        branch=[BranchFrame(fanout=fan.id, index=0, count=2, key="alpha")],
        result={"ok": "a"},
        terminal=True,
    )
    second = await task_at(
        store,
        run_id,
        "work",
        status=TaskStatus.done,
        branch=[BranchFrame(fanout=fan.id, index=1, count=2, key="beta")],
        result={"ok": "b"},
        terminal=True,
    )
    async with store.uow() as uow:
        await uow.runs.update(run_id, output=[{"ok": "a"}, {"ok": "b"}])

    body = (await client.get(f"/api/runs/{run_id}")).json()

    assert body["output"] == [{"ok": "a"}, {"ok": "b"}]
    assert body["outputs"] == [
        {
            "task_id": first.id,
            "node": "work",
            "branch": [{"index": 0, "key": "alpha"}],
            "value": {"ok": "a"},
        },
        {
            "task_id": second.id,
            "node": "work",
            "branch": [{"index": 1, "key": "beta"}],
            "value": {"ok": "b"},
        },
    ]
    terminal = {task["id"]: task["terminal"] for task in body["tasks"]}
    assert terminal[first.id] is True
    assert terminal[fan.id] is False


async def test_an_unknown_run_is_a_404_not_found(
    client: httpx.AsyncClient, registered: dict[str, Graph]
) -> None:
    response = await client.get("/api/runs/01JNOPE")

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


async def test_a_claimed_attempt_has_a_token_hash_the_wire_never_shows(
    client: httpx.AsyncClient, store: Store, registered: dict[str, Graph]
) -> None:
    """The walk on every response has something to find, and finds nothing.

    The claim mints a token and stores its SHA-256 (04 §Dispatch), so
    this run's task row *does* carry one — and neither the detail nor
    the list may say so (12 §Task tokens).
    """

    run_id = await submit(client)
    async with store.uow() as uow:
        (claimed,) = await uow.tasks.claim_ready(1, ["demo"])
    async with store.reader() as reader:
        stored = await reader.tasks.get(claimed.task.id)
    assert stored is not None and stored.token_hash is not None

    body = (await client.get(f"/api/runs/{run_id}")).json()

    assert body["status"] == RunStatus.running.value
    assert [task["status"] for task in body["tasks"]] == [TaskStatus.in_progress.value]
    assert not FORBIDDEN.intersection(keys(body))


# --------------------------------------------------------------------------
# PATCH — v0's test_edit_run.py
# --------------------------------------------------------------------------


async def test_patch_writes_the_fields_it_names_and_answers_with_the_detail(
    client: httpx.AsyncClient, registered: dict[str, Graph]
) -> None:
    run_id = await submit(client, title="before", description="also before")

    response = await client.patch(
        f"/api/runs/{run_id}", json={"title": "after", "description": "also after"}
    )

    assert response.status_code == 200
    assert response.json()["title"] == "after"
    assert response.json()["description"] == "also after"
    assert (await client.get(f"/api/runs/{run_id}")).json()["title"] == "after"


async def test_patch_leaves_the_field_it_omits_alone(
    client: httpx.AsyncClient, registered: dict[str, Graph]
) -> None:
    """An edit that sent no description must not blank one."""

    run_id = await submit(client, title="before", description="keep me")

    body = (await client.patch(f"/api/runs/{run_id}", json={"title": "after"})).json()

    assert body["title"] == "after"
    assert body["description"] == "keep me"


async def test_patch_with_neither_field_changes_nothing_and_still_answers(
    client: httpx.AsyncClient, registered: dict[str, Graph]
) -> None:
    """A patch is not the place to refuse a caller for being redundant."""

    run_id = await submit(client, title="unchanged", description="also unchanged")

    response = await client.patch(f"/api/runs/{run_id}", json={})

    assert response.status_code == 200
    assert response.json()["title"] == "unchanged"
    assert response.json()["description"] == "also unchanged"


async def test_patch_refuses_a_blank_title_with_a_422_naming_the_field(
    client: httpx.AsyncClient, registered: dict[str, Graph]
) -> None:
    """A run with no title is unfindable in every list that shows one."""

    run_id = await submit(client)

    response = await client.patch(f"/api/runs/{run_id}", json={"title": "   "})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation"
    assert body["errors"][0]["loc"] == ["body", "title"]


async def test_patch_of_an_unknown_run_is_a_404(
    client: httpx.AsyncClient, registered: dict[str, Graph]
) -> None:
    response = await client.patch("/api/runs/01JNOPE", json={"title": "x"})

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


# --------------------------------------------------------------------------
# pause / resume — the API half of v0's test_pause.py
# --------------------------------------------------------------------------


async def test_pause_then_resume_walks_the_run_state_machine(
    client: httpx.AsyncClient, registered: dict[str, Graph]
) -> None:
    run_id = await submit(client)

    paused = await client.post(f"/api/runs/{run_id}/pause")
    status_after_pause = (await client.get(f"/api/runs/{run_id}")).json()["status"]
    resumed = await client.post(f"/api/runs/{run_id}/resume")
    status_after_resume = (await client.get(f"/api/runs/{run_id}")).json()["status"]

    assert paused.status_code == 200
    assert paused.json() == {"ok": True, "note": None}
    assert status_after_pause == RunStatus.paused.value
    assert resumed.status_code == 200
    assert status_after_resume == RunStatus.running.value


async def test_pausing_a_paused_run_is_a_409_conflict(
    client: httpx.AsyncClient, registered: dict[str, Graph]
) -> None:
    run_id = await submit(client)
    await client.post(f"/api/runs/{run_id}/pause")

    response = await client.post(f"/api/runs/{run_id}/pause")

    assert response.status_code == 409
    assert response.json()["code"] == "conflict"


async def test_resuming_a_run_that_is_not_paused_is_a_409_conflict(
    client: httpx.AsyncClient, registered: dict[str, Graph]
) -> None:
    run_id = await submit(client)

    response = await client.post(f"/api/runs/{run_id}/resume")

    assert response.status_code == 409
    assert response.json()["code"] == "conflict"


@pytest.mark.parametrize("verb", ["pause", "resume", "cancel"])
async def test_the_verbs_404_on_an_unknown_run(
    client: httpx.AsyncClient, registered: dict[str, Graph], verb: str
) -> None:
    response = await client.post(f"/api/runs/01JNOPE/{verb}")

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


# --------------------------------------------------------------------------
# cancel / delete / rerun — the API half of v0's test_management.py
# --------------------------------------------------------------------------


async def test_cancel_stops_the_outstanding_attempts_and_says_how_many(
    client: httpx.AsyncClient, store: Store, registered: dict[str, Graph]
) -> None:
    run_id = await submit(client)
    await task_at(store, run_id, "build", status=TaskStatus.waiting)

    response = await client.post(f"/api/runs/{run_id}/cancel")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "note": "2 attempts cancelled"}
    body = (await client.get(f"/api/runs/{run_id}")).json()
    assert body["status"] == RunStatus.cancelled.value
    assert {task["status"] for task in body["tasks"]} == {TaskStatus.cancelled.value}


async def test_cancelling_a_run_that_has_already_ended_is_a_409(
    client: httpx.AsyncClient, registered: dict[str, Graph]
) -> None:
    run_id = await submit(client)
    await client.post(f"/api/runs/{run_id}/cancel")

    response = await client.post(f"/api/runs/{run_id}/cancel")

    assert response.status_code == 409
    assert response.json()["code"] == "conflict"


async def test_delete_answers_204_with_no_body_and_removes_the_run(
    client: httpx.AsyncClient, registered: dict[str, Graph]
) -> None:
    run_id = await submit(client)

    response = await client.delete(f"/api/runs/{run_id}")

    assert response.status_code == 204
    assert response.content == b""
    assert (await client.get(f"/api/runs/{run_id}")).status_code == 404
    assert (await client.get("/api/runs")).json() == []


async def test_rerun_enqueues_a_fresh_attempt_of_the_node(
    client: httpx.AsyncClient, store: Store, registered: dict[str, Graph]
) -> None:
    run_id = await submit(client)
    await task_at(store, run_id, "build", status=TaskStatus.dead_letter)

    response = await client.post(f"/api/runs/{run_id}/rerun", json={"node": "build"})

    assert response.status_code == 200
    task_id = response.json()["task_id"]
    tasks = {task.id: task for task in await store_tasks(store, run_id)}
    assert tasks[task_id].node == "build"
    assert tasks[task_id].attempt == 2
    assert tasks[task_id].status is TaskStatus.ready


async def test_rerun_of_a_node_the_workflow_does_not_have_is_a_404_unknown_node(
    client: httpx.AsyncClient, registered: dict[str, Graph]
) -> None:
    run_id = await submit(client)

    response = await client.post(f"/api/runs/{run_id}/rerun", json={"node": "ship"})

    assert response.status_code == 404
    assert response.json()["code"] == "unknown_node"


async def test_rerun_without_a_node_is_a_422(
    client: httpx.AsyncClient, registered: dict[str, Graph]
) -> None:
    run_id = await submit(client)

    response = await client.post(f"/api/runs/{run_id}/rerun", json={})

    assert response.status_code == 422
    assert response.json()["errors"][0]["loc"] == ["body", "node"]


# --------------------------------------------------------------------------
# position — the API half of v0's test_priority.py (D57)
# --------------------------------------------------------------------------


async def test_direction_swaps_with_the_neighbour(
    client: httpx.AsyncClient, registered: dict[str, Graph]
) -> None:
    first = await submit(client, title="first")
    second = await submit(client, title="second")

    response = await client.post(f"/api/runs/{second}/position", json={"direction": -1})

    assert response.status_code == 200
    assert response.json() == {"position": 1}
    assert await positions(client) == [(second, 1), (first, 2)]


async def test_direction_at_either_end_is_a_200_no_op(
    client: httpx.AsyncClient, registered: dict[str, Graph]
) -> None:
    """No neighbour, nothing moves, and the current position comes back."""

    first = await submit(client, title="first")
    second = await submit(client, title="second")

    top = await client.post(f"/api/runs/{first}/position", json={"direction": -1})
    bottom = await client.post(f"/api/runs/{second}/position", json={"direction": 1})

    assert (top.status_code, top.json()) == (200, {"position": 1})
    assert (bottom.status_code, bottom.json()) == (200, {"position": 2})
    assert await positions(client) == [(first, 1), (second, 2)]


async def test_index_is_zero_based_and_clamps_at_both_ends(
    client: httpx.AsyncClient, registered: dict[str, Graph]
) -> None:
    """D57: `{index: 0}` is New Run's "top", and the list is the bound."""

    first = await submit(client, title="first")
    second = await submit(client, title="second")
    third = await submit(client, title="third")

    to_top = await client.post(f"/api/runs/{third}/position", json={"index": 0})
    order_at_top = await positions(client)
    past_the_end = await client.post(f"/api/runs/{third}/position", json={"index": 99})
    order_at_end = await positions(client)
    below_zero = await client.post(f"/api/runs/{third}/position", json={"index": -7})

    assert to_top.json() == {"position": 1}
    assert order_at_top == [(third, 1), (first, 2), (second, 3)]
    assert past_the_end.json() == {"position": 3}
    assert order_at_end == [(first, 1), (second, 2), (third, 3)]
    assert below_zero.json() == {"position": 1}
    assert await positions(client) == [(third, 1), (first, 2), (second, 3)]


@pytest.mark.parametrize("body", [{}, {"direction": 1, "index": 0}, {"direction": 0}])
async def test_position_takes_exactly_one_of_direction_and_index(
    client: httpx.AsyncClient, registered: dict[str, Graph], body: dict[str, Any]
) -> None:
    """Refused by the body model, so `Ops.reorder`'s ValueError is unreachable."""

    run_id = await submit(client)

    response = await client.post(f"/api/runs/{run_id}/position", json=body)

    assert response.status_code == 422
    assert response.json()["code"] == "validation"


# --------------------------------------------------------------------------
# the work log — the API half of v0's test_run_log.py
# --------------------------------------------------------------------------


async def test_posting_a_note_writes_a_user_entry_under_the_current_node(
    client: httpx.AsyncClient, store: Store, registered: dict[str, Graph]
) -> None:
    run_id = await submit(client)
    await task_at(store, run_id, "build", status=TaskStatus.in_progress)

    posted = await client.post(f"/api/runs/{run_id}/log", json={"text": "look here"})
    entries = (await client.get(f"/api/runs/{run_id}/log")).json()

    assert posted.status_code == 200
    (entry,) = entries
    assert entry["id"] == posted.json()["log_id"]
    assert entry["author"] == "user"
    assert entry["node"] == "build"
    assert entry["task_id"] is None
    assert entry["text"] == "look here"
    assert entry["kind"] is None


async def test_a_note_with_no_node_in_flight_is_filed_under_user(
    client: httpx.AsyncClient, registered: dict[str, Graph]
) -> None:
    """Nothing is running, so there is no node to claim."""

    run_id = await submit(client)

    await client.post(f"/api/runs/{run_id}/log", json={"text": "before it starts"})

    (entry,) = (await client.get(f"/api/runs/{run_id}/log")).json()
    assert entry["node"] == "user"


@pytest.mark.parametrize("body", [{"text": "   "}, {"text": ""}, {}])
async def test_a_note_needs_text(
    client: httpx.AsyncClient, registered: dict[str, Graph], body: dict[str, Any]
) -> None:
    run_id = await submit(client)

    response = await client.post(f"/api/runs/{run_id}/log", json=body)

    assert response.status_code == 422
    assert response.json()["errors"][0]["loc"] == ["body", "text"]


async def test_the_log_of_an_unknown_run_is_a_404(
    client: httpx.AsyncClient, registered: dict[str, Graph]
) -> None:
    read = await client.get("/api/runs/01JNOPE/log")
    written = await client.post("/api/runs/01JNOPE/log", json={"text": "hello"})

    assert read.status_code == 404
    assert written.status_code == 404


async def test_the_log_carries_the_engines_own_entries_too(
    client: httpx.AsyncClient, store: Store, registered: dict[str, Graph]
) -> None:
    """Operator information the agent view drops (08 §Agent-facing)."""

    run_id = await submit(client)
    async with store.uow() as uow:
        await uow.log.append(
            run_id=run_id,
            node="build",
            author="engine",
            text="[stats] 120 tokens",
            kind="stats",
        )

    (entry,) = (await client.get(f"/api/runs/{run_id}/log")).json()

    assert entry["author"] == "engine"
    assert entry["kind"] == "stats"


# --------------------------------------------------------------------------
# events and requests
# --------------------------------------------------------------------------


async def test_the_event_page_is_the_typed_envelope_of_18(
    client: httpx.AsyncClient, registered: dict[str, Graph]
) -> None:
    """The shape the SSE feed sends, from history (D53)."""

    run_id = await submit(client, title="watch me")

    body = (await client.get(f"/api/runs/{run_id}/events")).json()

    assert [event["name"] for event in body] == ["run.created", "task.enqueued"]
    created, enqueued = body
    assert created["run_id"] == run_id
    assert created["data"] == {
        "workflow": "demo",
        "title": "watch me",
        "position": 1,
    }
    assert enqueued["data"]["node"] == "plan"
    assert enqueued["data"]["reason"] == "start"


async def test_the_event_page_takes_after_and_limit(
    client: httpx.AsyncClient, registered: dict[str, Graph]
) -> None:
    run_id = await submit(client)
    every = (await client.get(f"/api/runs/{run_id}/events")).json()

    first = await client.get(f"/api/runs/{run_id}/events", params={"limit": 1})
    rest = await client.get(
        f"/api/runs/{run_id}/events", params={"after": every[0]["id"]}
    )
    too_many = await client.get(f"/api/runs/{run_id}/events", params={"limit": 100_000})

    assert [event["id"] for event in first.json()] == [every[0]["id"]]
    assert [event["id"] for event in rest.json()] == [every[1]["id"]]
    assert too_many.status_code == 422


async def test_a_runs_requests_are_its_whole_history_not_the_inbox(
    client: httpx.AsyncClient, store: Store, registered: dict[str, Graph]
) -> None:
    """A stale request stays here and leaves the inbox (06 §Restart)."""

    run_id = await submit(client)
    live = await task_at(store, run_id, "build", status=TaskStatus.waiting)
    gone = await task_at(store, run_id, "review", status=TaskStatus.dead_letter)
    async with store.uow() as uow:
        await uow.requests.create(
            run_id, live.id, "still open?", mode="text", source="node", kind="question"
        )
        await uow.requests.create(
            run_id, gone.id, "too late", mode="text", source="node", kind="question"
        )

    body = (await client.get(f"/api/runs/{run_id}/requests")).json()

    assert [view["prompt"] for view in body] == ["still open?", "too late"]
    assert [view["pending"] for view in body] == [True, False]
    assert [view["stale"] for view in body] == [False, True]
    assert (await client.get(f"/api/runs/{run_id}")).json()["pending_requests"] == 1


# --------------------------------------------------------------------------
# the graph: state precedence
# --------------------------------------------------------------------------


def node_of(body: dict[str, Any], name: str) -> dict[str, Any]:
    """One node of a `/graph` body."""

    return next(node for node in body["nodes"] if node["name"] == name)


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ([TaskStatus.done, TaskStatus.in_progress, TaskStatus.waiting], "in_progress"),
        ([TaskStatus.done, TaskStatus.waiting, TaskStatus.ready], "waiting"),
        ([TaskStatus.failed, TaskStatus.ready], "ready"),
        ([TaskStatus.dead_letter, TaskStatus.failed, TaskStatus.done], "dead_letter"),
        ([TaskStatus.failed, TaskStatus.done], "failed"),
        ([TaskStatus.done, TaskStatus.cancelled], "done"),
        ([TaskStatus.cancelled], "cancelled"),
        ([], "idle"),
    ],
)
async def test_node_state_follows_08s_precedence_first_match_wins(
    client: httpx.AsyncClient,
    store: Store,
    registered: dict[str, Graph],
    statuses: list[TaskStatus],
    expected: str,
) -> None:
    """08 §Graph semantics' table, row by row.

    The third row is the one 17 §T044a names: a failed attempt with a
    retry still pending reports `ready`, because the retry row exists.
    """

    run_id = await submit(client)
    for attempt, status in enumerate(statuses, start=1):
        await task_at(store, run_id, "build", status=status, attempt=attempt)

    body = (await client.get(f"/api/runs/{run_id}/graph")).json()

    assert node_of(body, "build")["state"] == expected


async def test_a_node_counts_its_attempts_and_names_the_last(
    client: httpx.AsyncClient, store: Store, registered: dict[str, Graph]
) -> None:
    run_id = await submit(client)
    first = await task_at(store, run_id, "build", status=TaskStatus.failed, attempt=1)
    second = await task_at(store, run_id, "build", status=TaskStatus.ready, attempt=2)

    node = node_of((await client.get(f"/api/runs/{run_id}/graph")).json(), "build")

    assert node["attempts"] == 2
    assert node["last_task_id"] == second.id
    assert node["branches"] == [{"from_task": None, "tasks": [first.id, second.id]}]


@pytest.mark.parametrize(
    ("status", "live"),
    [
        (TaskStatus.in_progress, True),
        (TaskStatus.waiting, True),
        (TaskStatus.done, True),
        (TaskStatus.ready, False),
        (TaskStatus.failed, False),
        (TaskStatus.cancelled, False),
    ],
)
async def test_live_is_in_flight_or_ever_done(
    client: httpx.AsyncClient,
    store: Store,
    registered: dict[str, Graph],
    status: TaskStatus,
    live: bool,
) -> None:
    """The liveness flag `node`-slot plugin panels read (09 §Slots)."""

    run_id = await submit(client)
    await task_at(store, run_id, "build", status=status)

    node = node_of((await client.get(f"/api/runs/{run_id}/graph")).json(), "build")

    assert node["live"] is live
    assert (
        node_of((await client.get(f"/api/runs/{run_id}/graph")).json(), "review")[
            "live"
        ]
        is False
    )


async def test_an_untouched_node_is_idle_with_no_attempts(
    client: httpx.AsyncClient, registered: dict[str, Graph]
) -> None:
    run_id = await submit(client)

    node = node_of((await client.get(f"/api/runs/{run_id}/graph")).json(), "review")

    assert node["state"] == "idle"
    assert node["attempts"] == 0
    assert node["last_task_id"] is None
    assert node["branches"] == []
    assert node["arrivals"] is None


# --------------------------------------------------------------------------
# the graph: shape, branches, joins, edges
# --------------------------------------------------------------------------


async def test_the_graph_lists_nodes_in_generation_order_with_their_edges(
    client: httpx.AsyncClient, registered: dict[str, Graph]
) -> None:
    """Forward edges, and the loop back drawn as a rail (10 §Graph pane)."""

    run_id = await submit(client)

    body = (await client.get(f"/api/runs/{run_id}/graph")).json()

    assert [node["name"] for node in body["nodes"]] == ["plan", "build", "review"]
    assert [node["generation"] for node in body["nodes"]] == [0, 1, 2]
    assert body["edges"] == [
        {"from": "plan", "to": "build", "kind": "forward", "traversed": 0},
        {"from": "build", "to": "review", "kind": "forward", "traversed": 0},
        {"from": "review", "to": "build", "kind": "back", "traversed": 0},
    ]


async def test_an_edge_into_a_join_is_a_join_edge(
    client: httpx.AsyncClient, registered: dict[str, Graph]
) -> None:
    run_id = await submit(client, "fanout")

    body = (await client.get(f"/api/runs/{run_id}/graph")).json()

    assert body["edges"] == [
        {"from": "split", "to": "work", "kind": "forward", "traversed": 0},
        {"from": "work", "to": "gather", "kind": "join", "traversed": 0},
    ]
    assert [node["join"] for node in body["nodes"]] == [False, False, True]


async def test_traversed_counts_transitions_and_arrivals(
    client: httpx.AsyncClient, store: Store, registered: dict[str, Graph]
) -> None:
    """08 §Graph semantics: `task.enqueued reason=transition`, plus
    `join.arrived` on a join edge — a transition into a join enqueues
    nothing until the last branch lands."""

    run_id = await submit(client, "fanout")
    fan = (await store_tasks(store, run_id))[0]
    branches = [
        await task_at(
            store,
            run_id,
            "work",
            status=TaskStatus.done,
            branch=[BranchFrame(fanout=fan.id, index=index, count=3, key=index)],
        )
        for index in range(3)
    ]
    await transitioned(store, run_id, fan.id, "work", times=3)
    for index, branch in enumerate(branches[:2]):
        await emit(
            store,
            run_id,
            branch.id,
            EventName.join_arrived,
            join="gather",
            fanout_task=fan.id,
            index=index,
            count=3,
            arrived=index + 1,
            late=False,
        )

    body = (await client.get(f"/api/runs/{run_id}/graph")).json()

    crossings = {
        (edge["from"], edge["to"]): edge["traversed"] for edge in body["edges"]
    }

    assert crossings == {("split", "work"): 3, ("work", "gather"): 2}


async def test_a_fan_out_run_reports_one_branch_per_branch(
    client: httpx.AsyncClient, store: Store, registered: dict[str, Graph]
) -> None:
    """The indented sub-lists of 10 §Graph pane, one per branch."""

    run_id = await submit(client, "fanout")
    fan = (await store_tasks(store, run_id))[0]
    branches = [
        await task_at(
            store,
            run_id,
            "work",
            status=TaskStatus.done,
            branch=[BranchFrame(fanout=fan.id, index=index, count=3, key=index)],
        )
        for index in range(3)
    ]
    retry = await task_at(
        store,
        run_id,
        "work",
        status=TaskStatus.ready,
        attempt=2,
        branch=[BranchFrame(fanout=fan.id, index=1, count=3, key=1)],
    )

    node = node_of((await client.get(f"/api/runs/{run_id}/graph")).json(), "work")

    assert node["attempts"] == 4
    assert node["branches"] == [
        {"from_task": fan.id, "tasks": [branches[0].id]},
        {"from_task": fan.id, "tasks": [branches[1].id, retry.id]},
        {"from_task": fan.id, "tasks": [branches[2].id]},
    ]
    assert node_of((await client.get(f"/api/runs/{run_id}/graph")).json(), "split")[
        "branches"
    ] == [{"from_task": None, "tasks": [fan.id]}]


async def test_a_join_with_a_fan_out_still_open_reports_two_of_three(
    client: httpx.AsyncClient, store: Store, registered: dict[str, Graph]
) -> None:
    """`2 of 3 arrived`, from `JoinRepo.incomplete` (10 §Graph pane)."""

    run_id = await submit(client, "fanout")
    fan = (await store_tasks(store, run_id))[0]
    branches = [
        await task_at(
            store,
            run_id,
            "work",
            status=TaskStatus.done,
            branch=[BranchFrame(fanout=fan.id, index=index, count=3, key=index)],
        )
        for index in range(3)
    ]
    async with store.uow() as uow:
        for index, branch in enumerate(branches[:2]):
            await uow.joins.arrive(
                run_id=run_id,
                join_node="gather",
                fanout_task=fan.id,
                index=index,
                key=index,
                value={"from": index},
                from_task=branch.id,
                count=3,
            )

    node = node_of((await client.get(f"/api/runs/{run_id}/graph")).json(), "gather")

    assert node["join"] is True
    assert node["arrivals"] == {"arrived": 2, "count": 3}


async def test_a_join_whose_fan_out_completed_reports_no_arrivals(
    client: httpx.AsyncClient, store: Store, registered: dict[str, Graph]
) -> None:
    """`arrivals` is for a fan-out that is still open, and this one is not."""

    run_id = await submit(client, "fanout")
    fan = (await store_tasks(store, run_id))[0]
    async with store.uow() as uow:
        for index in range(2):
            branch = await uow.tasks.enqueue(
                run_id,
                "work",
                None,
                0,
                False,
                branch=[BranchFrame(fanout=fan.id, index=index, count=2, key=index)],
            )
            await uow.joins.arrive(
                run_id=run_id,
                join_node="gather",
                fanout_task=fan.id,
                index=index,
                key=index,
                value=None,
                from_task=branch.id,
                count=2,
            )

    node = node_of((await client.get(f"/api/runs/{run_id}/graph")).json(), "gather")

    assert node["arrivals"] is None


async def test_the_graph_of_a_run_whose_workflow_is_not_registered_is_a_404(
    client: httpx.AsyncClient, store: Store, registered: dict[str, Graph]
) -> None:
    """No graph to project onto; the run list says so with `unregistered`."""

    async with store.uow() as uow:
        orphan = await uow.runs.insert("ghost", "left behind")

    response = await client.get(f"/api/runs/{orphan.id}/graph")

    assert response.status_code == 404
    assert response.json()["code"] == "unknown_workflow"


async def test_the_graph_of_an_unknown_run_is_a_404(
    client: httpx.AsyncClient, registered: dict[str, Graph]
) -> None:
    response = await client.get("/api/runs/01JNOPE/graph")

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"

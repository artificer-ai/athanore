"""The five core-shipped panes, declared through the plugin API (T050, 09).

Driven the way a plugin is driven: `builtin_spec()` handed to
`create_app` beside a workflow's own spec, and the routes called over
ASGI through the operator door. If a builtin needed something a
workflow's plugin does not get, that would show up here as a fixture this
suite could not build — which is the claim 09 makes when it calls the
builtins "the proof the API is sufficient".

Three assertions carry the task. The manifest lists the builtins first
and in the order 09 tables them. The overview's totals are
`RunDetail.stats` — two paths to the same numbers, and a dashboard that
quietly disagreed with the run page would be worse than one that showed
nothing. And the log pane interleaves the work log with the run's events
by time, because either one alone is a story with holes in it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

import httpx
import pytest

from athanore.events.model import Event
from athanore.events.names import EventName
from athanore.graph import GraphError
from athanore.plugins.builtin import (
    BUILTIN_MODULES,
    BuiltinWorkflow,
    builtin_spec,
    builtin_workflow,
    with_builtins,
)
from athanore.plugins.builtin import log as log_builtin
from athanore.plugins.context import PluginContext
from athanore.plugins.registry import BUILTIN_WORKFLOW, PluginSpec, collect, validate
from athanore.store.clock import now
from athanore.store.rows import EventRow, LogAuthor, LogEntryRow, LogKind, TaskStatus
from athanore.store.uow import Store
from athanore.workflow import Workflow

#: The panels the builtins declare, in the order they are declared —
#: overview, log, agent, requests (run pane and inbox), graph.
PANELS = ["overview", "log", "agent", "requests", "inbox", "graph"]

AppFactory = Callable[..., Awaitable[httpx.AsyncClient]]


def gamedev() -> Workflow:
    """A two-node workflow with a plugin panel of its own."""

    wf = Workflow("gamedev")

    @wf.node(start=True)
    async def play(review):
        """Play one round."""
        return review("athanor")

    @wf.node()
    async def review(*, word):
        """Read it back."""
        return word

    @wf.route("/words")
    async def words(ctx: PluginContext) -> dict:
        """Every word this run has used."""
        return {"run_id": ctx.run_id}

    wf.panel("Words", slot="run", kind="table", source=words)
    return wf


def other() -> Workflow:
    """A second workflow, so ownership has something to be wrong about."""

    wf = Workflow("other")

    @wf.node(start=True)
    async def only():
        return None

    return wf


async def submit(client: httpx.AsyncClient, workflow: str = "gamedev") -> str:
    """Queue a run through the API, and return its id."""

    response = await client.post(
        f"/api/workflows/{workflow}/runs",
        json={"title": "a run", "description": "the long version"},
    )
    assert response.status_code == 201, response.text
    return response.json()["run_id"]


async def overview_of(client: httpx.AsyncClient, run_id: str) -> dict[str, Any]:
    """The overview pane's data for one run."""

    response = await client.get(
        "/api/plugins/_builtin/overview", params={"run_id": run_id}
    )
    assert response.status_code == 200, response.text
    return response.json()


async def log_of(
    client: httpx.AsyncClient, run_id: str, **params: Any
) -> list[dict[str, Any]]:
    """The log pane's rows for one run."""

    response = await client.get(
        "/api/plugins/_builtin/log", params={"run_id": run_id, **params}
    )
    assert response.status_code == 200, response.text
    return response.json()


# -- the manifest -----------------------------------------------------------


async def test_the_manifest_lists_the_builtins_first_and_in_order(
    app_with: AppFactory,
) -> None:
    """09 §Mounting: builtins first, then the workflows in registration order."""

    client = await app_with(gamedev(), extra=[builtin_spec()])

    body = (await client.get("/api/plugins")).json()

    assert [entry["workflow"] for entry in body] == [BUILTIN_WORKFLOW, "gamedev"]
    assert [panel["name"] for panel in body[0]["panels"]] == PANELS


async def test_the_builtin_panels_carry_their_kinds_and_their_sources(
    app_with: AppFactory,
) -> None:
    """The manifest is what the SPA lays the panes out from (09 §Wire)."""

    client = await app_with(gamedev(), extra=[builtin_spec()])

    panels = {
        panel["name"]: panel
        for panel in (await client.get("/api/plugins")).json()[0]["panels"]
    }

    assert panels["overview"]["kind"] == "dashboard"
    assert panels["overview"]["source"] == "/api/plugins/_builtin/overview"
    assert panels["log"]["kind"] == "log"
    assert panels["log"]["refresh_on"] == ["log.appended", "task.*"]
    assert panels["agent"]["element"] == "ath-agent-stream"
    assert panels["requests"]["element"] == "ath-requests"
    assert panels["graph"]["element"] == "ath-run-graph"
    # The inbox is the one builtin pane that is not about a run (09).
    assert panels["inbox"]["slot"] == "global"
    assert panels["inbox"]["scope"] == "global"
    # A custom panel names no source: its element fetches for itself.
    assert "source" not in panels["graph"]


def test_with_builtins_puts_the_builtin_spec_in_front() -> None:
    """What a host hands `create_app(plugins=…)`."""

    mine = PluginSpec(workflow="gamedev")

    composed = with_builtins([mine])

    assert [spec.workflow for spec in composed] == [BUILTIN_WORKFLOW, "gamedev"]


def test_the_builtin_spec_passes_the_registrys_own_checks() -> None:
    """A builtin goes through the six checks a workflow's plugin does."""

    workflow = builtin_workflow()

    spec = collect(workflow)
    validate(spec, workflow.finalize())

    assert spec.workflow == BUILTIN_WORKFLOW
    assert len(BUILTIN_MODULES) == 5
    assert [route.path for route in spec.routes] == ["/overview", "/log"]


def test_the_builtin_scope_declares_panes_not_nodes() -> None:
    """`_builtin` is a namespace for declarations, not a workflow."""

    workflow = BuiltinWorkflow()

    with pytest.raises(GraphError, match="no nodes"):

        @workflow.node(start=True)
        async def never():  # pragma: no cover - the decorator raises first
            return None

    assert workflow.finalize().nodes == {}


def test_a_declaration_after_finalize_is_refused_here_too() -> None:
    """The same rule a workflow has (09 §Registration)."""

    workflow = builtin_workflow()
    workflow.finalize()

    with pytest.raises(GraphError, match="already finalized"):
        workflow.panel("late", slot="run", kind="markdown")


# -- the overview pane ------------------------------------------------------


async def test_the_overview_totals_are_the_runs_totals(
    app_with: AppFactory, store: Store
) -> None:
    """The dashboard and `GET /api/runs/{id}` read the same numbers."""

    client = await app_with(gamedev(), extra=[builtin_spec()])
    run_id = await submit(client)
    (start,) = await tasks_of(store, run_id)
    async with store.uow() as uow:
        await uow.tasks.set_stats(
            start.id, {"total_tokens": 120, "cost": 0.25, "session_id": "s-01"}
        )

    body = await overview_of(client, run_id)
    stats = (await client.get(f"/api/runs/{run_id}")).json()["stats"]

    metrics = {metric["label"]: metric["value"] for metric in body["metrics"]}
    assert metrics["TOKENS"] == stats["total_tokens"] == 120
    assert metrics["COST"] == pytest.approx(stats["cost"]) == pytest.approx(0.25)


async def test_the_overview_omits_what_no_attempt_reported(
    app_with: AppFactory,
) -> None:
    """01 §Real data only: fewer tiles, not tiles claiming zero."""

    client = await app_with(gamedev(), extra=[builtin_spec()])
    run_id = await submit(client)

    body = await overview_of(client, run_id)

    labels = [metric["label"] for metric in body["metrics"]]
    assert labels == ["DURATION", "POSITION"]
    assert "SESSION" not in body["meta"]
    assert "AGENTS" not in body["meta"]


async def test_the_overview_metrics_are_in_the_order_10_draws_them(
    app_with: AppFactory, store: Store
) -> None:
    client = await app_with(gamedev(), extra=[builtin_spec()])
    run_id = await submit(client)
    (start,) = await tasks_of(store, run_id)
    async with store.uow() as uow:
        await uow.tasks.set_stats(start.id, {"total_tokens": 7, "cost": 0.5})

    body = await overview_of(client, run_id)

    assert [metric["label"] for metric in body["metrics"]] == [
        "TOKENS",
        "COST",
        "DURATION",
        "POSITION",
    ]


async def test_the_overview_position_is_the_place_in_the_dispatch_list(
    app_with: AppFactory,
) -> None:
    client = await app_with(gamedev(), extra=[builtin_spec()])
    first = await submit(client)
    second = await submit(client)

    metrics = {
        metric["label"]: metric["value"]
        for metric in (await overview_of(client, second))["metrics"]
    }

    assert metrics["POSITION"] == "2 of 2"
    assert (await overview_of(client, first))["metrics"][-1]["value"] == "1 of 2"


async def test_the_overview_tables_one_row_per_node_it_has_entered(
    app_with: AppFactory, store: Store
) -> None:
    """ATT collapses the attempts; a node never reached has no row."""

    client = await app_with(gamedev(), extra=[builtin_spec()])
    run_id = await submit(client)
    async with store.uow() as uow:
        (start,) = await uow.tasks.list_for_run(run_id)
        await uow.tasks.set_stats(start.id, {"total_tokens": 30})
        await uow.tasks.set_status(start.id, TaskStatus.failed.value)
        retry = await uow.tasks.enqueue(
            run_id, "play", None, priority=0, explicit=False, attempt=2
        )
        await uow.tasks.set_stats(retry.id, {"total_tokens": 12})

    body = await overview_of(client, run_id)

    assert [column["key"] for column in body["table"]["columns"]] == [
        "node",
        "attempts",
        "status",
        "tokens",
        "duration_s",
    ]
    assert body["table"]["rows"] == [
        {"node": "play", "attempts": 2, "status": "ready", "tokens": 42}
    ]


async def test_the_overview_meta_is_the_kv_grid_of_10(
    app_with: AppFactory, store: Store
) -> None:
    client = await app_with(gamedev(), extra=[builtin_spec()])
    run_id = await submit(client)
    (start,) = await tasks_of(store, run_id)
    async with store.uow() as uow:
        await uow.tasks.set_stats(start.id, {"session_id": "0198c0de-cafe"})
        await uow.tasks.set_status(start.id, TaskStatus.in_progress.value)

    body = await overview_of(client, run_id)

    meta = body["meta"]
    assert meta["RUN"] == run_id
    assert meta["WORKFLOW"] == "gamedev"
    assert meta["TITLE"] == "a run"
    assert meta["STATUS"] == "queued · play"
    assert meta["SESSION"] == "0198c0de-cafe"
    assert meta["AGENTS"] == 1
    assert meta["DESCRIPTION"] == "the long version"
    assert body["note"] == "the long version"
    assert meta["AGE"] >= 0


async def test_the_builtin_scope_reads_every_workflows_runs(
    app_with: AppFactory,
) -> None:
    """09: the builtins' panels apply to every run, so they own every run."""

    client = await app_with(gamedev(), other(), extra=[builtin_spec()])
    run_id = await submit(client, "other")

    body = await overview_of(client, run_id)

    assert body["meta"]["WORKFLOW"] == "other"
    assert body["metrics"][-1]["value"] == "1 of 1"


async def test_an_overview_of_a_run_that_does_not_exist_is_404(
    app_with: AppFactory,
) -> None:
    client = await app_with(gamedev(), extra=[builtin_spec()])

    response = await client.get(
        "/api/plugins/_builtin/overview", params={"run_id": "01JQNOTAREALRUN000000000"}
    )

    assert response.status_code == 404
    assert response.json()["code"] == "plugin_error"


async def test_the_overview_needs_a_run(app_with: AppFactory) -> None:
    """A run pane's route without a run is the refusal of 09 §Context."""

    client = await app_with(gamedev(), extra=[builtin_spec()])

    response = await client.get("/api/plugins/_builtin/overview")

    assert response.status_code == 400
    assert response.json()["error"] == "no run in scope"


# -- the log pane -----------------------------------------------------------


async def test_the_log_interleaves_entries_and_events_by_time(
    app_with: AppFactory, store: Store
) -> None:
    """One ordered stream: the work log and what the engine did between."""

    client = await app_with(gamedev(), extra=[builtin_spec()])
    run_id = await submit(client)
    (start,) = await tasks_of(store, run_id)
    async with store.uow() as uow:
        first = await uow.log.append(
            run_id, "play", LogAuthor.agent.value, "the deliverable"
        )
    async with store.uow() as uow:
        second = await uow.log.append(run_id, "review", LogAuthor.user.value, "a note")
    assert second.created > first.created, "the two entries share a timestamp"
    # Between the two entries, which is the whole point: read on its own,
    # neither list says the attempt finished in between.
    async with store.uow() as uow:
        uow.emit(
            Event(
                run_id=run_id,
                task_id=start.id,
                name=EventName.task_done.value,
                data={
                    "node": "play",
                    "attempt": 1,
                    "transitions": ["review"],
                    "terminal": False,
                },
                created=first.created + (second.created - first.created) / 2,
            )
        )

    rows = await log_of(client, run_id)

    assert [row["text"] for row in rows[-3:]] == [
        "the deliverable",
        "attempt 1 done → review",
        "a note",
    ]
    assert [row["source"] for row in rows[-3:]] == [
        "play/agent",
        "play/engine",
        "review/user",
    ]
    assert [row["ts"] for row in rows] == sorted(row["ts"] for row in rows)
    # The run's own history is in the same list, before all three.
    assert rows[0]["text"] == "run created in gamedev at position 1"


def test_merge_orders_by_time_and_reads_an_entry_before_its_event() -> None:
    """The unit of the merge: time first, and the entry before the event."""

    stamp = now()
    entries = [
        _entry(2, stamp + timedelta(seconds=2), "second"),
        _entry(1, stamp, "first"),
    ]
    events = [
        _event(9, stamp + timedelta(seconds=1), EventName.run_paused.value, {}),
        # The same instant as the first entry: the entry is the thing that
        # happened, the event announces it.
        _event(8, stamp, EventName.run_started.value, {"task_id": 1, "node": "play"}),
    ]

    rows = log_builtin.merge(entries, events, {})

    assert [row["text"] for row in rows] == [
        "first",
        "run started at play",
        "run paused",
        "second",
    ]


def test_the_log_leaves_out_the_events_other_panes_own() -> None:
    """10 §Panes: the stream, the requests and the stats belong elsewhere."""

    stamp = now()
    hidden = [
        _event(1, stamp, EventName.task_stream.value, {"seq_from": 1, "seq_to": 2}),
        _event(2, stamp, EventName.log_appended.value, {"log_id": 1}),
        _event(3, stamp, EventName.agent_stats.value, {"node": "play"}),
        _event(4, stamp, EventName.request_opened.value, {"request_id": 1}),
        _event(5, stamp, EventName.submission_accepted.value, {"node": "play"}),
    ]

    assert log_builtin.merge([], hidden, {}) == []


def test_an_edge_reads_as_the_two_nodes_it_joins() -> None:
    """10 §Panes' own example: `engineering → qa`."""

    event = _event(
        1,
        now(),
        EventName.task_enqueued.value,
        {
            "node": "qa",
            "attempt": 1,
            "reason": "transition",
            "from_task": 7,
            "payload_present": False,
            "branch": [],
        },
    )

    assert log_builtin.sentence(event, {7: "engineering"}) == "engineering → qa"


def test_a_failure_reads_as_one_line() -> None:
    """`attempt 2 failed: …`, and never the whole traceback."""

    event = _event(
        1,
        now(),
        EventName.task_failed.value,
        {
            "node": "qa",
            "attempt": 2,
            "error": "boom\n  File ...\n  File ...",
            "retryable": True,
            "will_retry": True,
        },
    )

    assert log_builtin.sentence(event, {}) == "attempt 2 failed: boom, retrying"


def test_an_event_with_no_phrasing_of_its_own_reads_as_its_name() -> None:
    """A vocabulary 03 grew before this module did still renders."""

    event = _event(1, now(), "engine.recovered", {"task_ids": []})

    assert log_builtin.sentence(event, {}) == "engine.recovered"


def test_a_payload_the_phrasing_cannot_read_falls_back_to_the_name() -> None:
    """A row an older process wrote is a line, not a 500 for the pane."""

    event = _event(1, now(), EventName.task_done.value, {})

    assert log_builtin.sentence(event, {}) == EventName.task_done.value


async def test_the_log_tones_the_stats_lines_and_the_engines(
    app_with: AppFactory, store: Store
) -> None:
    """10 §Panes' tone mapping, on real entries."""

    client = await app_with(gamedev(), extra=[builtin_spec()])
    run_id = await submit(client)
    async with store.uow() as uow:
        await uow.log.append(
            run_id,
            "play",
            LogAuthor.engine.value,
            "[stats] node=play attempt=1 ok",
            kind=LogKind.stats.value,
        )
        await uow.log.append(
            run_id,
            "play",
            LogAuthor.engine.value,
            "attempt 1 failed",
            kind=LogKind.failure.value,
        )
        await uow.log.append(run_id, "play", LogAuthor.agent.value, "a deliverable")

    rows = await log_of(client, run_id)

    assert [row["level"] for row in rows[-3:]] == ["accent", "dim", "default"]


async def test_the_log_limit_takes_the_most_recent_lines(
    app_with: AppFactory, store: Store
) -> None:
    client = await app_with(gamedev(), extra=[builtin_spec()])
    run_id = await submit(client)
    async with store.uow() as uow:
        for text in ("one", "two", "three"):
            await uow.log.append(run_id, "play", LogAuthor.user.value, text)

    rows = await log_of(client, run_id, limit=2)

    assert [row["text"] for row in rows] == ["two", "three"]
    assert len(await log_of(client, run_id)) > 3


# -- helpers ----------------------------------------------------------------


async def tasks_of(store: Store, run_id: str) -> list[Any]:
    """Every attempt of a run, oldest first."""

    async with store.reader() as reader:
        return await reader.tasks.list_for_run(run_id)


def _entry(id_: int, created: Any, text: str) -> LogEntryRow:
    return LogEntryRow(
        id=id_,
        run_id="01JQRUN",
        task_id=None,
        node="play",
        author=LogAuthor.user,
        kind=None,
        text=text,
        created=created,
    )


def _event(id_: int, created: Any, name: str, data: dict[str, Any]) -> EventRow:
    return EventRow(id=id_, run_id="01JQRUN", name=name, data=data, created=created)

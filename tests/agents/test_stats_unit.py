"""The stats entry: built honestly, formatted, and recorded exactly once.

05 §Stats entry and D46. The pure halves — :func:`usage_from_acp`,
:func:`merge_usage`, :func:`build_entry`, :func:`format_stats_line` — are
ported from the MVP's ``tests/test_stats.py``; the session-file parsing
that suite also covers is a provider concern now and moves to
``examples/tests/test_pi_stats.py`` with the pi provider (T040, D27).

Two properties are asserted everywhere rather than in one place:

**Absent, not zero.** Every assertion about an unknown field is that the
*key is not in the entry*, not that it is ``None``. `AGENTS.md` §Real data
only is a claim about what a summary of a hundred runs means, and a
``None`` that a later ``or 0`` turns into a number is the same lie as the
zero, one layer further along.

**Recorded against a real store.** :func:`record_entry` writes a log row,
a column and an event in one transaction, so the suite reads all three
back out of SQLite. A stubbed service would let this file agree with
itself about a transaction that never ran.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, get_args

import pytest
from pydantic import ValidationError
from structlog.testing import capture_logs

from athanore.agents.stats import (
    SessionStats,
    StatsReason,
    build_entry,
    format_stats_line,
    merge_usage,
    record_entry,
    usage_from_acp,
)
from athanore.engine.context import TaskContext
from athanore.engine.services import TaskServices
from athanore.events.names import EventName
from athanore.events.payloads import AgentStats
from athanore.store.rows import LogAuthor, LogKind
from athanore.store.uow import Store

Make = Callable[..., Awaitable[TaskContext]]

#: A session id shaped like the ULIDs a real agent hands back, so that the
#: log line's eight-character abbreviation abbreviates something.
SID = "01a012f7-d9d7-700e-8661-04d982431e5c"

MODEL = "llama-server/qwen3.8-27b"


class Usage:
    """What an ACP ``PromptResponse.usage`` looks like: an object."""

    def __init__(self, input_tokens: int, output_tokens: int, total: int) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.total_tokens = total


# --------------------------------------------------------------------------
# usage_from_acp
# --------------------------------------------------------------------------


def test_usage_is_read_off_an_object_or_a_mapping() -> None:
    """Adapters hand back either; both are the same three counters."""

    counted = {"input_tokens": 1000, "output_tokens": 500, "total_tokens": 1500}

    assert usage_from_acp(Usage(1000, 500, 1500)) == counted
    assert usage_from_acp(counted) == counted


def test_no_usage_at_all_is_no_measurement() -> None:
    """``usage`` is UNSTABLE and absent from some adapters (05)."""

    assert usage_from_acp(None) is None
    assert usage_from_acp(object()) is None


def test_a_partial_usage_is_refused_rather_than_completed() -> None:
    """Two of three counters is a shape this does not know how to read."""

    assert usage_from_acp({"input_tokens": 1}) is None
    assert usage_from_acp({"input_tokens": 1, "output_tokens": 2}) is None


def test_a_bool_is_not_a_token_count() -> None:
    """``True`` is an ``int`` to Python and a mistake here."""

    assert (
        usage_from_acp({"input_tokens": True, "output_tokens": 2, "total_tokens": 3})
        is None
    )


# --------------------------------------------------------------------------
# merge_usage
# --------------------------------------------------------------------------


def test_acp_wins_for_tokens_and_the_provider_supplies_cost() -> None:
    """The precedence of 05, fixed here so no call site decides it."""

    merged = merge_usage(
        {"input_tokens": 1000, "output_tokens": 500, "total_tokens": 1500},
        SessionStats(model=MODEL, input_tokens=7, output_tokens=3, cost=0.25),
    )

    assert merged == {
        "input_tokens": 1000,
        "output_tokens": 500,
        "total_tokens": 1500,
        "cost": 0.25,
        "model": MODEL,
    }


def test_the_provider_supplies_tokens_when_acp_sent_none() -> None:
    """The other way round: no ACP usage, so the session file is it."""

    merged = merge_usage(None, SessionStats(input_tokens=100, output_tokens=50))

    assert merged == {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150}


def test_acp_usage_stands_on_its_own() -> None:
    """Real data the agent sent, with no provider configured at all."""

    merged = merge_usage(
        {"input_tokens": 40, "output_tokens": 20, "total_tokens": 60}, None
    )

    assert merged == {"input_tokens": 40, "output_tokens": 20, "total_tokens": 60}


def test_a_zero_acp_total_is_derived_from_the_two_sides() -> None:
    """An adapter that filled ``total`` with a number it did not measure."""

    merged = merge_usage(
        {"input_tokens": 40, "output_tokens": 20, "total_tokens": 0}, None
    )

    assert merged is not None
    assert merged["total_tokens"] == 60


def test_a_one_sided_provider_yields_no_total() -> None:
    """Half a sum is not a total, so the key stays out."""

    merged = merge_usage(None, SessionStats(output_tokens=4))

    assert merged == {"output_tokens": 4}


def test_a_provider_with_only_a_cost_still_reports_it() -> None:
    """Cost has one source, and it is independent of the token counts."""

    assert merge_usage(None, SessionStats(cost=0.0)) == {"cost": 0.0}


def test_nothing_from_either_source_is_nothing() -> None:
    assert merge_usage(None, None) is None
    assert merge_usage(None, SessionStats()) is None


# --------------------------------------------------------------------------
# build_entry
# --------------------------------------------------------------------------


def test_a_complete_entry_carries_every_measurement() -> None:
    entry = build_entry(
        node="product",
        attempt=1,
        status="ok",
        duration_s=142.4,
        model="the-class-model",
        usage=merge_usage(
            {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
            SessionStats(model=MODEL, cost=0.0),
        ),
        tool_calls=23,
        session_id=SID,
        repair_turns=1,
        denied_permissions=2,
    )

    assert entry == {
        "node": "product",
        "attempt": 1,
        "status": "ok",
        "session_id": SID,
        "duration_s": 142,
        "tool_calls": 23,
        "repair_turns": 1,
        "denied_permissions": 2,
        "input_tokens": 100,
        "output_tokens": 50,
        "total_tokens": 150,
        "cost": 0.0,
        "model": MODEL,
    }


def test_unknown_fields_are_absent_not_none() -> None:
    """The whole point: a key that is not there cannot be summed."""

    entry = build_entry(node="qa", attempt=2, status="failed", duration_s=1.2)

    assert entry == {
        "node": "qa",
        "attempt": 2,
        "status": "failed",
        "duration_s": 1,
    }
    for field in (
        "reason",
        "model",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "tool_calls",
        "cost",
        "session_id",
        "repair_turns",
        "denied_permissions",
    ):
        assert field not in entry


def test_a_failure_carries_its_reason() -> None:
    entry = build_entry(
        node="qa", attempt=2, status="failed", duration_s=3, reason="timeout"
    )

    assert entry["status"] == "failed"
    assert entry["reason"] == "timeout"


def test_the_class_model_is_the_fallback_and_the_provider_beats_it() -> None:
    """What was asked for, against what answered (05, D11)."""

    asked = build_entry(
        node="x", attempt=1, status="ok", duration_s=1, model="asked-for"
    )
    answered = build_entry(
        node="x",
        attempt=1,
        status="ok",
        duration_s=1,
        model="asked-for",
        usage=merge_usage(None, SessionStats(model=MODEL)),
    )

    assert asked["model"] == "asked-for"
    assert answered["model"] == MODEL


def test_a_real_zero_is_data() -> None:
    """No tool call and a free model are measurements, not unknowns."""

    entry = build_entry(
        node="x",
        attempt=1,
        status="ok",
        duration_s=0.4,
        tool_calls=0,
        usage=merge_usage(None, SessionStats(cost=0.0)),
    )

    assert entry["tool_calls"] == 0
    assert entry["cost"] == 0.0
    assert entry["duration_s"] == 0


def test_counts_of_none_are_left_out() -> None:
    """No repair to report on a run that needed none (05: "when > 0")."""

    entry = build_entry(
        node="x",
        attempt=1,
        status="ok",
        duration_s=1,
        repair_turns=0,
        denied_permissions=0,
    )

    assert "repair_turns" not in entry
    assert "denied_permissions" not in entry


def test_a_one_sided_provider_writes_no_total() -> None:
    entry = build_entry(
        node="x",
        attempt=1,
        status="ok",
        duration_s=1,
        usage=merge_usage(None, SessionStats(output_tokens=4)),
    )

    assert entry["output_tokens"] == 4
    assert "input_tokens" not in entry
    assert "total_tokens" not in entry


def test_an_entry_is_18s_payload() -> None:
    """Built here, validated at the publisher: the two must agree."""

    entry = build_entry(
        node="qa",
        attempt=2,
        status="failed",
        duration_s=3,
        reason="truncated",
        usage=merge_usage(None, SessionStats(model=MODEL, cost=1.5)),
        tool_calls=7,
        session_id=SID,
        repair_turns=2,
        denied_permissions=1,
    )

    assert AgentStats.model_validate(entry).model_dump() == entry


def test_the_reason_vocabulary_is_18s() -> None:
    """One list, stated twice because the tiers may not import each other."""

    published = AgentStats.model_fields["reason"].annotation
    literal = next(arg for arg in get_args(published) if arg is not type(None))

    assert set(get_args(StatsReason)) == set(get_args(literal))


# --------------------------------------------------------------------------
# format_stats_line
# --------------------------------------------------------------------------


def test_the_line_is_05s_example() -> None:
    line = format_stats_line(
        {
            "node": "qa",
            "attempt": 2,
            "status": "ok",
            "model": MODEL,
            "input_tokens": 12406,
            "output_tokens": 1204,
            "total_tokens": 13610,
            "tool_calls": 23,
            "repair_turns": 1,
            "cost": 0.0,
            "duration_s": 142,
            "session_id": SID,
        }
    )

    assert line == (
        f"[stats] node=qa attempt=2 ok — model={MODEL}, "
        "tokens=12,406 in / 1,204 out / 13,610 total, tools=23 calls, "
        "repairs=1, cost=$0.0000, 142s, session=01a012f7"
    )


def test_a_failed_line_names_the_reason_in_parentheses() -> None:
    line = format_stats_line(
        {"node": "qa", "attempt": 2, "status": "failed", "reason": "timeout"}
    )

    assert line == "[stats] node=qa attempt=2 failed (timeout)"


def test_the_line_omits_what_the_entry_omits() -> None:
    line = format_stats_line(
        build_entry(node="x", attempt=1, status="ok", duration_s=2, tool_calls=4)
    )

    assert line == "[stats] node=x attempt=1 ok — tools=4 calls, 2s"
    assert "model=" not in line
    assert "tokens=" not in line
    assert "cost=" not in line
    assert "session=" not in line


def test_the_line_invents_no_zeros() -> None:
    """An entry with no measurements has no digit but its attempt."""

    line = format_stats_line({"node": "x", "attempt": 1, "status": "ok"})

    assert "0" not in line


def test_a_missing_side_of_a_token_pair_is_the_n_marker() -> None:
    """``n`` is 05's not-available marker; ``0 out`` would read as data."""

    incoming = format_stats_line(
        {"node": "x", "attempt": 1, "status": "ok", "input_tokens": 10}
    )
    outgoing = format_stats_line(
        {"node": "x", "attempt": 1, "status": "ok", "output_tokens": 5}
    )

    assert "tokens=10 in / n out" in incoming
    assert "0 out" not in incoming
    assert "tokens=n in / 5 out" in outgoing
    assert "0 in" not in outgoing


# --------------------------------------------------------------------------
# record_entry
# --------------------------------------------------------------------------


def entry_for(node: str = "build", **overrides: Any) -> dict[str, Any]:
    """A modest entry, of the shape a finished ``run()`` produces."""

    fields: dict[str, Any] = {
        "node": node,
        "attempt": 1,
        "status": "ok",
        "duration_s": 12.0,
        "tool_calls": 2,
        "session_id": SID,
        "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
    }
    fields.update(overrides)
    return build_entry(**fields)


async def log_rows(store: Store, run_id: str) -> list[Any]:
    async with store.reader() as reader:
        return await reader.log.list(run_id)


async def events_named(store: Store, run_id: str, name: str) -> list[Any]:
    async with store.reader() as reader:
        rows = await reader.events.list_for_run(run_id)
    return [row for row in rows if row.name == name]


async def test_recording_writes_the_line_the_column_and_the_event(
    context: Make, store: Store
) -> None:
    """05's three destinations, from one call."""

    ctx = await context()
    entry = entry_for()

    assert await record_entry(ctx, entry) is True

    rows = await log_rows(store, ctx.run_id)
    assert len(rows) == 1
    assert rows[0].author == LogAuthor.engine
    assert rows[0].kind == LogKind.stats
    assert rows[0].node == ctx.node
    assert rows[0].task_id == ctx.task_id
    assert rows[0].text == format_stats_line(entry)

    async with store.reader() as reader:
        task = await reader.tasks.get(ctx.task_id)
    assert task is not None
    assert task.stats == entry

    published = await events_named(store, ctx.run_id, EventName.agent_stats)
    assert len(published) == 1
    assert published[0].task_id == ctx.task_id
    assert published[0].data == entry


async def test_the_stats_line_is_announced_like_any_other_entry(
    context: Make, store: Store
) -> None:
    """``log.appended`` is what refreshes the log pane (10 §Realtime)."""

    ctx = await context()

    await record_entry(ctx, entry_for())

    announced = await events_named(store, ctx.run_id, EventName.log_appended)
    assert len(announced) == 1
    assert announced[0].data["kind"] == str(LogKind.stats)
    assert announced[0].data["author"] == str(LogAuthor.engine)
    assert announced[0].data["preview"].startswith("[stats] node=build attempt=1 ok")


async def test_the_event_omits_what_the_entry_omits(
    context: Make, store: Store
) -> None:
    """No zero-fill survives the trip through 18's payload."""

    ctx = await context()

    entry = build_entry(node="build", attempt=1, status="ok", duration_s=1)
    await record_entry(ctx, entry)

    published = await events_named(store, ctx.run_id, EventName.agent_stats)
    assert published[0].data == {
        "node": "build",
        "attempt": 1,
        "status": "ok",
        "duration_s": 1.0,
    }


async def test_recording_the_same_entry_twice_writes_one_row(
    context: Make, store: Store
) -> None:
    """The ``finally`` of a ``run()`` that already recorded on its way out."""

    ctx = await context()
    entry = entry_for()

    assert await record_entry(ctx, entry) is True
    assert await record_entry(ctx, entry) is False

    assert len(await log_rows(store, ctx.run_id)) == 1
    assert len(await events_named(store, ctx.run_id, EventName.agent_stats)) == 1


async def test_two_agents_in_one_attempt_each_record_their_own(
    context: Make, store: Store
) -> None:
    """The guard is the entry, not the task: a body may run two agents."""

    ctx = await context()
    first = entry_for(session_id="01a00000-first")
    second = entry_for(session_id="01a00000-second")

    assert await record_entry(ctx, first) is True
    assert await record_entry(ctx, second) is True

    rows = await log_rows(store, ctx.run_id)
    assert len(rows) == 2
    async with store.reader() as reader:
        task = await reader.tasks.get(ctx.task_id)
    assert task is not None
    assert task.stats == second


async def test_recording_outside_a_task_context_logs_the_numbers() -> None:
    """An agent run with no task has nowhere to write, and says so."""

    entry = entry_for()

    with capture_logs() as logs:
        assert await record_entry(None, entry) is False

    assert [line["event"] for line in logs] == [
        "agent stats recorded outside a task context"
    ]
    assert logs[0]["log_level"] == "warning"
    assert logs[0]["stats"] == entry


async def test_a_failed_write_is_logged_and_leaves_nothing_behind(
    context: Make, store: Store
) -> None:
    """One transaction: the line, the column and the event roll back together.

    The task the services point at does not exist, so the log insert
    breaks a foreign key. What matters is that the caller is handed a
    ``False`` rather than an exception — this runs in the ``finally`` of a
    façade, where a raise would replace the outcome the body earned.
    """

    ctx = await context()
    orphan = TaskContext(
        run_id=ctx.run_id,
        task_id=ctx.task_id + 1000,
        workflow=ctx.workflow,
        node=ctx.node,
        attempt=1,
        token=ctx.token,
        api_base=ctx.api_base,
        services=TaskServices(
            store,
            run_id=ctx.run_id,
            task_id=ctx.task_id + 1000,
            node=ctx.node,
            workflow=ctx.workflow,
            flush_interval=0.05,
        ),
    )

    with capture_logs() as logs:
        assert await record_entry(orphan, entry_for()) is False

    assert [line["event"] for line in logs] == ["agent stats could not be recorded"]
    assert logs[0]["log_level"] == "error"
    assert await log_rows(store, ctx.run_id) == []
    assert await events_named(store, ctx.run_id, EventName.agent_stats) == []


async def test_an_entry_18_would_refuse_never_reaches_a_consumer(
    context: Make, store: Store
) -> None:
    """Drift from the vocabulary fails at the publisher, not downstream."""

    ctx = await context()

    with capture_logs() as logs:
        assert await record_entry(ctx, {"node": "build", "status": "elated"}) is False

    assert [line["event"] for line in logs] == ["agent stats could not be recorded"]
    assert await log_rows(store, ctx.run_id) == []


async def test_the_service_itself_raises(context: Make) -> None:
    """``record_entry`` swallows; the service it calls does not (05)."""

    ctx = await context()

    with pytest.raises(ValidationError):
        await ctx.services.stats.record({"node": "build"}, text="[stats] node=build")

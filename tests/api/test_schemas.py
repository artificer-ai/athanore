"""The wire models: the fields 08 fixes, and the one field that must not exist.

Two kinds of assertion here, and they are different jobs.

**The contract.** Each model's field names are written out as 08 §Runs,
§Tasks and §Requests list them. That is what OpenAPI publishes and what
the generated TypeScript client hands the SPA, so a field added or
renamed without a change to the document fails here first.

**The drift.** Every field these models fill from a store read model is
checked to exist on that read model. The API declares its own schemas
rather than serialising the store's (`athanore.api.schemas`), which is
what keeps a column change from silently becoming a contract change — and
this is the other half of that arrangement: the two are checked against
each other on purpose rather than by accident.

`TaskView` gets a third: it has **no** `token_hash` field at all, and a
recursive walk over a converted row proves no token reaches the wire (12
§Task tokens).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from athanore.api import schemas
from athanore.events import payloads
from athanore.store import rows

STAMP = datetime(2026, 9, 7, 14, 2, 11, tzinfo=UTC)


def field_names(model: type[BaseModel]) -> set[str]:
    """The model's fields under the names they carry on the wire."""

    return {
        field.serialization_alias or name for name, field in model.model_fields.items()
    }


def walk(value: Any) -> list[str]:
    """Every key anywhere in ``value``, however deeply nested."""

    if isinstance(value, dict):
        keys: list[str] = []
        for key, item in value.items():
            keys.append(str(key))
            keys.extend(walk(item))
        return keys
    if isinstance(value, (list, tuple)):
        return [key for item in value for key in walk(item)]
    return []


# -- fixtures ---------------------------------------------------------------


def a_task(**overrides: Any) -> rows.TaskRow:
    """A stored task with every column filled, including its token hash."""

    values: dict[str, Any] = dict(
        id=7,
        run_id="01JRUN",
        node="build",
        attempt=2,
        status=rows.TaskStatus.done,
        payload={"title": "ship it"},
        result={"ok": True},
        error=None,
        priority=-1,
        explicit=False,
        token_hash="a" * 64,
        stats={"total_tokens": 120},
        lineage={"reason": "transition", "from": 6},
        terminal=True,
        branch=[rows.BranchFrame(fanout=5, index=1, count=3, key="beta")],
        created=STAMP,
        started=STAMP,
        finished=STAMP,
    )
    values.update(overrides)
    return rows.TaskRow(**values)


def a_run(**overrides: Any) -> rows.RunSummary:
    values: dict[str, Any] = dict(
        id="01JRUN",
        workflow="demo",
        title="ship it",
        description="the whole thing",
        status=rows.RunStatus.running,
        output={"ok": True},
        position=3,
        created=STAMP,
        updated=STAMP,
        finished=None,
        current_nodes=["build"],
        pending_requests=1,
        unregistered=False,
    )
    values.update(overrides)
    return rows.RunSummary(**values)


def a_request(**overrides: Any) -> rows.RequestView:
    values: dict[str, Any] = dict(
        id=4,
        run_id="01JRUN",
        task_id=7,
        node="build",
        prompt="Ship it?",
        mode=rows.RequestMode.options,
        source=rows.RequestSource.agent,
        kind=rows.RequestKind.permission,
        options=[{"option_id": "yes", "name": "Yes", "kind": "allow_once"}],
        schema_=None,
        tool_call={"title": "write"},
        pending=True,
        stale=False,
        answer=None,
        answered_by=None,
        created=STAMP,
        age=1.5,
    )
    values.update(overrides)
    return rows.RequestView(**values)


# -- the task, and the token that is not on it ------------------------------


def test_a_task_view_has_no_token_field_to_leak() -> None:
    """The store excludes `token_hash`; this model does not have one."""

    assert "token_hash" not in schemas.TaskView.model_fields
    assert "token" not in schemas.TaskView.model_fields
    assert "token_hash" not in schemas.TaskDetail.model_fields


def test_a_converted_task_carries_no_token_anywhere() -> None:
    """A recursive walk, not a spot check on the top level."""

    view = schemas.TaskView.of(a_task())

    keys = walk(view.model_dump(mode="json"))
    assert "token_hash" not in keys
    assert "token" not in keys
    assert "branch" in keys


def test_a_task_view_is_the_stored_row_without_its_token() -> None:
    """08 §Tasks: `TaskRow` (no tokens), with `terminal` and `branch`."""

    assert field_names(schemas.TaskView) == field_names(rows.TaskRow) - {"token_hash"}

    view = schemas.TaskView.of(a_task())
    assert view.terminal is True
    assert view.branch == [schemas.BranchFrame(fanout=5, index=1, count=3, key="beta")]
    assert view.status is rows.TaskStatus.done
    assert view.stats == {"total_tokens": 120}


def test_a_task_detail_adds_the_submissions() -> None:
    """08 §Tasks: the task plus its submissions, in the operator view."""

    submission = rows.SubmissionRow(id=2, task_id=7, payload={"n": 1}, created=STAMP)

    detail = schemas.TaskDetail.of_task(a_task(), [submission])

    assert field_names(schemas.TaskDetail) == field_names(schemas.TaskView) | {
        "submissions"
    }
    assert detail.id == 7
    assert [one.id for one in detail.submissions] == [2]
    assert "token_hash" not in walk(detail.model_dump(mode="json"))


# -- runs -------------------------------------------------------------------


def test_a_run_summary_is_08s_list_row() -> None:
    assert field_names(schemas.RunSummary) == {
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
    assert field_names(schemas.RunSummary) <= field_names(rows.RunSummary)

    summary = schemas.RunSummary.of(a_run())
    assert summary.current_nodes == ["build"]
    assert summary.pending_requests == 1


def test_a_run_detail_is_the_summary_plus_what_the_overview_shows() -> None:
    """08 §Runs: description, output, tasks and the stats totals."""

    assert field_names(schemas.RunDetail) == field_names(schemas.RunSummary) | {
        "description",
        "output",
        "outputs",
        "tasks",
        "stats",
    }


def test_a_run_detail_derives_its_outputs_from_the_terminal_tasks() -> None:
    """`outputs` is always a list, one entry per terminal task (D58)."""

    terminal = a_task(id=9, node="review", terminal=True, result="done")
    ordinary = a_task(id=8, node="build", terminal=False, result="ignored")

    detail = schemas.RunDetail.of_run(
        a_run(), tasks=[ordinary, terminal], stats=rows.RunStats(total_tokens=120)
    )

    assert [one.model_dump() for one in detail.outputs] == [
        {
            "task_id": 9,
            "node": "review",
            "branch": [{"index": 1, "key": "beta"}],
            "value": "done",
        }
    ]
    assert [task.id for task in detail.tasks] == [8, 9]
    assert detail.description == "the whole thing"
    assert detail.output == {"ok": True}


def test_a_run_with_no_terminal_task_has_no_outputs() -> None:
    """A list, always — empty rather than absent (D58)."""

    detail = schemas.RunDetail.of_run(
        a_run(), tasks=[a_task(terminal=False)], stats=rows.RunStats()
    )

    assert detail.outputs == []


def test_the_stats_totals_are_never_zero_filled() -> None:
    """A provider that measured nothing leaves the field out (01)."""

    assert field_names(schemas.RunStats) == field_names(rows.RunStats)

    stats = schemas.RunStats.of(rows.RunStats(total_tokens=120))
    assert stats.total_tokens == 120
    assert stats.cost is None
    assert stats.model_dump(exclude_none=True) == {"total_tokens": 120}


def test_a_log_entry_is_the_stored_entry() -> None:
    row = rows.LogEntryRow(
        id=3,
        run_id="01JRUN",
        task_id=7,
        node="build",
        author=rows.LogAuthor.agent,
        kind=rows.LogKind.deliverable,
        text="built it",
        created=STAMP,
    )

    assert field_names(schemas.LogEntry) == field_names(rows.LogEntryRow)
    entry = schemas.LogEntry.of(row)
    assert entry.author is rows.LogAuthor.agent
    assert entry.kind is rows.LogKind.deliverable
    assert entry.text == "built it"


# -- the graph view ---------------------------------------------------------


def test_the_node_states_are_08s_precedence_in_order() -> None:
    """First match wins, and the member order *is* the rule (08 §Graph)."""

    assert [state.value for state in schemas.NodeState] == [
        "in_progress",
        "waiting",
        "ready",
        "dead_letter",
        "failed",
        "done",
        "cancelled",
        "idle",
    ]
    # Every task status is reachable as a node state, plus `idle` for a
    # node with no task at all.
    assert {state.value for state in schemas.NodeState} == {
        status.value for status in rows.TaskStatus
    } | {"idle"}


def test_a_graph_edge_serialises_from_under_the_name_08_fixes() -> None:
    """`from` is a Python keyword; the wire name is not negotiable."""

    edge = schemas.GraphEdge(
        from_="build", to="review", kind=schemas.EdgeKind.forward, traversed=2
    )

    assert edge.model_dump(by_alias=True) == {
        "from": "build",
        "to": "review",
        "kind": "forward",
        "traversed": 2,
    }
    assert (
        schemas.GraphEdge.model_validate(
            {"from": "build", "to": "plan", "kind": "back", "traversed": 1}
        ).from_
        == "build"
    )


def test_the_graph_reports_a_joins_open_arrivals() -> None:
    """`2 of 3 arrived`, for the innermost pending fan-out (10 §Graph pane)."""

    node = schemas.GraphNode(
        name="collect",
        generation=2,
        join=True,
        state=schemas.NodeState.idle,
        live=False,
        attempts=0,
        branches=[schemas.GraphBranch(from_task=5, tasks=[7, 8])],
        arrivals=schemas.Arrivals(arrived=2, count=3),
    )

    dumped = node.model_dump()
    assert dumped["arrivals"] == {"arrived": 2, "count": 3}
    assert dumped["last_task_id"] is None
    assert dumped["branches"] == [{"from_task": 5, "tasks": [7, 8]}]


# -- requests ---------------------------------------------------------------


def test_a_request_view_is_08s_field_list() -> None:
    assert field_names(schemas.RequestView) == {
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
    assert field_names(schemas.RequestView) == field_names(rows.RequestView)


def test_a_request_view_types_its_options_and_aliases_its_schema() -> None:
    """The three keys 06 §The model fixes, and `schema` on the wire."""

    view = schemas.RequestView.of(a_request(schema_={"type": "object"}))

    dumped = view.model_dump(by_alias=True)
    assert dumped["options"] == [
        {"option_id": "yes", "name": "Yes", "kind": "allow_once"}
    ]
    assert dumped["schema"] == {"type": "object"}
    assert "schema_" not in dumped


def test_a_request_view_keeps_pending_and_stale_apart() -> None:
    """Neither is "not the other": an answered request is neither (06)."""

    answered = schemas.RequestView.of(
        a_request(
            pending=False,
            stale=False,
            answer="yes",
            answered_by=rows.AnswerAuthor.user,
        )
    )
    stale = schemas.RequestView.of(a_request(pending=False, stale=True))

    assert (answered.pending, answered.stale) == (False, False)
    assert answered.answered_by is rows.AnswerAuthor.user
    assert (stale.pending, stale.stale) == (False, True)
    # `answered_by` is the field to test for having an answer at all.
    assert stale.answered_by is None


def test_a_request_view_with_no_options_stays_absent() -> None:
    """A `text` request offers nothing, and null is not an empty list."""

    view = schemas.RequestView.of(a_request(mode=rows.RequestMode.text, options=None))

    assert view.options is None


# -- the event envelope -----------------------------------------------------


def test_the_event_envelope_is_re_exported_and_not_restated() -> None:
    """18 §Typing, D81: one declaration, below the API, shared with the bus."""

    assert schemas.EventEnvelope is payloads.EventEnvelope


# -- request bodies ---------------------------------------------------------


def test_a_new_run_strips_its_title_and_refuses_an_empty_one() -> None:
    assert schemas.NewRun(title="  ship it  ").title == "ship it"
    assert schemas.NewRun(title="x").description == ""
    for blank in ("", "   "):
        with pytest.raises(ValidationError):
            schemas.NewRun(title=blank)


def test_an_edit_leaves_out_what_it_does_not_change() -> None:
    """An absent field is left alone; it is not blanked (08 §Runs)."""

    edit = schemas.EditRun(description="new words")

    assert edit.title is None
    assert edit.model_dump(exclude_unset=True) == {"description": "new words"}
    # An edit that names nothing changes nothing, exactly as `Ops.edit`
    # treats it.
    assert schemas.EditRun().model_dump(exclude_unset=True) == {}


def test_a_position_takes_exactly_one_of_direction_and_index() -> None:
    """D57, and the refusal `Ops.reorder` would otherwise raise as a 500."""

    assert schemas.Position(direction=-1).direction == -1
    assert schemas.Position(index=0).index == 0
    for bad in ({}, {"direction": 1, "index": 0}, {"direction": 2}):
        with pytest.raises(ValidationError):
            schemas.Position.model_validate(bad)


def test_a_log_entry_body_refuses_whitespace() -> None:
    assert schemas.LogText(text=" a note ").text == "a note"
    with pytest.raises(ValidationError):
        schemas.LogText(text="   ")


def test_the_node_bodies_name_a_node() -> None:
    assert schemas.Rerun(node=" build ").node == "build"
    assert schemas.Move(node="review").node == "review"
    with pytest.raises(ValidationError):
        schemas.Move(node="")


def test_set_status_accepts_only_the_three_an_operator_may_write() -> None:
    """The other four are the engine's record of what happened (08 §Tasks)."""

    for status in ("ready", "cancelled", "dead_letter"):
        assert schemas.SetStatus.model_validate({"status": status}).status == status
    for refused in ("done", "in_progress", "failed", "waiting"):
        with pytest.raises(ValidationError):
            schemas.SetStatus.model_validate({"status": refused})


def test_an_answer_carries_an_option_or_a_value() -> None:
    """Which one is expected is the request's `mode`, not the body's shape."""

    assert schemas.Answer(option_id="yes").option_id == "yes"
    assert schemas.Answer(value={"n": 1}).value == {"n": 1}
    # A `null` answer is a value an author could have given, so an empty
    # body is well-formed and the service decides.
    assert schemas.Answer().model_dump() == {"option_id": None, "value": None}


# -- acknowledgements -------------------------------------------------------


def test_the_acknowledgements_name_the_id_08_returns() -> None:
    assert schemas.Ok().model_dump(exclude_none=True) == {"ok": True}
    assert schemas.Ok(note="already paused").note == "already paused"
    assert schemas.Created(run_id="01JRUN").model_dump() == {"run_id": "01JRUN"}
    assert schemas.TaskRef(task_id=7).model_dump() == {"task_id": 7}
    assert schemas.LogRef(log_id=3).model_dump() == {"log_id": 3}


def test_a_stream_page_says_how_far_it_got_and_whether_more_is_coming() -> None:
    """`last_seq` is the store's highest, not the page's (08 §Tasks)."""

    chunk = rows.StreamChunkRow(
        id=1, task_id=7, seq=4, kind=rows.ChunkKind.text, text="hello", created=STAMP
    )

    page = schemas.StreamOut(
        chunks=[schemas.StreamChunk.of(chunk)], last_seq=9, live=True
    )

    assert page.model_dump()["chunks"] == [
        {"seq": 4, "kind": "text", "text": "hello", "created": STAMP}
    ]
    assert (page.last_seq, page.live) == (9, True)

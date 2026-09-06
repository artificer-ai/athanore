"""Tests for :mod:`athanore.store.rows` — the domain enums and read models.

Two of these are security and honesty properties rather than typing
checks, and they are the reason this module has tests at all: a
``token_hash`` that serializes leaks a credential into an operator
response (12 §Task tokens), and a :class:`RunStats` that zero-fills
reports token counts nobody measured (01 §Real data only).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from athanore.store.rows import (
    AnswerAuthor,
    AnswerRow,
    BranchFrame,
    ChunkKind,
    EventRow,
    LogAuthor,
    LogEntryRow,
    LogKind,
    ReadModel,
    RequestKind,
    RequestMode,
    RequestRow,
    RequestSource,
    RequestView,
    RunRow,
    RunStats,
    RunStatus,
    RunSummary,
    StreamChunkRow,
    SubmissionRow,
    TaskRow,
    TaskStatus,
)

NOW = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)

ROW_MODELS = [
    RunRow,
    RunSummary,
    RunStats,
    BranchFrame,
    TaskRow,
    LogEntryRow,
    SubmissionRow,
    StreamChunkRow,
    RequestRow,
    AnswerRow,
    RequestView,
    EventRow,
]


def make_task(**overrides: object) -> TaskRow:
    fields: dict[str, object] = {
        "id": 7,
        "run_id": "01J9Z0000000000000000000AB",
        "node": "implement",
        "attempt": 2,
        "status": TaskStatus.in_progress,
        "payload": {"deliverable": "the parser"},
        "priority": -1,
        "explicit": False,
        "token_hash": "a" * 64,
        "created": NOW,
        "started": NOW,
    }
    fields.update(overrides)
    return TaskRow.model_validate(fields)


# --------------------------------------------------------------------------
# Enums
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("enum", "values"),
    [
        (RunStatus, "queued running paused completed failed cancelled"),
        (TaskStatus, "ready in_progress waiting done failed dead_letter cancelled"),
        (LogAuthor, "agent engine user"),
        (LogKind, "deliverable note stats failure"),
        (ChunkKind, "text thought tool_call tool_result notice"),
        (RequestMode, "options form text"),
        (RequestSource, "agent node"),
        (RequestKind, "permission elicitation question"),
        (AnswerAuthor, "user engine"),
    ],
)
def test_enum_members_are_exactly_the_specified_values(
    enum: type[str], values: str
) -> None:
    """03 fixes each vocabulary; a member added or dropped fails here."""
    assert [member.value for member in enum] == values.split()  # type: ignore[attr-defined]
    assert [member.name for member in enum] == values.split()  # type: ignore[attr-defined]


def test_enums_are_str_enums() -> None:
    """Statuses cross the wire and the SQL boundary as their values."""
    assert TaskStatus.dead_letter == "dead_letter"
    assert f"{RunStatus.queued}" == "queued"


# --------------------------------------------------------------------------
# The two properties worth a test
# --------------------------------------------------------------------------


def test_task_row_never_serializes_its_token_hash() -> None:
    """12 §Task tokens: the API cannot leak what the model will not dump."""
    task = make_task()

    assert task.token_hash == "a" * 64
    assert "token_hash" not in task.model_dump()
    assert "token_hash" not in task.model_dump(mode="json")
    assert "token_hash" not in task.model_dump_json()


def test_task_row_carries_no_clear_text_token_field() -> None:
    """The token itself is never stored (07 §Schema), so there is no field."""
    assert "token" not in TaskRow.model_fields


def test_run_stats_omits_what_was_not_measured() -> None:
    """01 §Real data only: unknown is absent, never zero."""
    assert RunStats().model_dump(exclude_none=True) == {}
    assert all(value is None for value in RunStats().model_dump().values())

    partial = RunStats(input_tokens=120, output_tokens=48, total_tokens=168)
    assert partial.model_dump(exclude_none=True) == {
        "input_tokens": 120,
        "output_tokens": 48,
        "total_tokens": 168,
    }


# --------------------------------------------------------------------------
# Read models
# --------------------------------------------------------------------------


@pytest.mark.parametrize("model", ROW_MODELS)
def test_every_read_model_is_frozen(model: type[ReadModel]) -> None:
    assert model.model_config.get("frozen") is True


def test_a_frozen_row_refuses_assignment() -> None:
    task = make_task()
    with pytest.raises(ValidationError):
        task.status = TaskStatus.done  # type: ignore[misc]


def test_task_row_parses_its_branch_frames() -> None:
    """04 §Branch frames: outermost first, ``key`` the branch's identity."""
    task = make_task(
        branch=[
            {"fanout": 3, "index": 0, "count": 2, "key": {"deliverable": "parser"}},
            {"fanout": 9, "index": 1, "count": 4, "key": "b"},
        ]
    )

    assert [frame.index for frame in task.branch] == [0, 1]
    assert task.branch[0].key == {"deliverable": "parser"}
    assert isinstance(task.branch[1], BranchFrame)


def test_task_row_defaults_are_the_column_defaults() -> None:
    """07 §Schema: ``terminal`` false, ``branch`` empty, the rest NULL."""
    task = make_task(token_hash=None, payload=None, started=None)

    assert task.terminal is False
    assert task.branch == []
    assert (task.result, task.error, task.stats, task.lineage) == (
        None,
        None,
        None,
        None,
    )
    assert task.finished is None


def test_branch_defaults_are_not_shared_between_rows() -> None:
    first = make_task(id=1)
    second = make_task(id=2)

    assert first.branch is not second.branch


def test_run_summary_is_a_run_plus_its_aggregates() -> None:
    """08 §Runs: the list endpoint's shape, from one grouped query."""
    summary = RunSummary(
        id="01J9Z0000000000000000000AB",
        workflow="v1_feature",
        title="T010",
        status=RunStatus.running,
        position=3,
        created=NOW,
        updated=NOW,
        current_nodes=["implement", "qa"],
        pending_requests=2,
    )

    assert isinstance(summary, RunRow)
    assert summary.current_nodes == ["implement", "qa"]
    assert summary.pending_requests == 2
    assert summary.unregistered is False


def test_run_row_distinguishes_a_null_output_from_an_unfinished_run() -> None:
    fields = {
        "id": "01J9Z0000000000000000000AB",
        "workflow": "v1_feature",
        "title": "T010",
        "status": RunStatus.completed,
        "position": 1,
        "created": NOW,
        "updated": NOW,
    }
    running = RunRow.model_validate({**fields, "status": RunStatus.running})
    completed = RunRow.model_validate({**fields, "finished": NOW})

    assert (running.output, running.finished) == (None, None)
    assert (completed.output, completed.finished) == (None, NOW)


def test_request_row_keeps_schema_as_the_wire_name() -> None:
    """The column 08 spells ``schema`` cannot be a pydantic field name."""
    by_alias = RequestRow.model_validate(
        {
            "id": 4,
            "run_id": "01J9Z0000000000000000000AB",
            "task_id": 7,
            "prompt": "Which deliverable?",
            "mode": RequestMode.form,
            "source": RequestSource.node,
            "kind": RequestKind.question,
            "schema": {"type": "object"},
            "created": NOW,
        }
    )
    by_name = RequestRow(
        id=4,
        run_id="01J9Z0000000000000000000AB",
        task_id=7,
        prompt="Which deliverable?",
        mode=RequestMode.form,
        source=RequestSource.node,
        kind=RequestKind.question,
        schema_={"type": "object"},
        created=NOW,
    )

    assert by_alias.schema_ == {"type": "object"}
    assert by_alias == by_name
    assert by_alias.model_dump(by_alias=True)["schema"] == {"type": "object"}
    assert by_alias.ordinal is None


def test_request_and_answer_carry_the_shapes_of_06() -> None:
    request = RequestRow(
        id=4,
        run_id="01J9Z0000000000000000000AB",
        task_id=7,
        ordinal=1,
        prompt="Allow writing to the repository?",
        mode=RequestMode.options,
        source=RequestSource.agent,
        kind=RequestKind.permission,
        options=[{"option_id": "allow_once", "name": "Allow once", "kind": "allow"}],
        tool_call={"toolCallId": "call_1"},
        created=NOW,
    )
    answer = AnswerRow(
        request_id=request.id,
        author=AnswerAuthor.engine,
        option_id="allow_once",
        created=NOW,
    )

    assert request.options is not None
    assert request.options[0]["option_id"] == "allow_once"
    assert (answer.value, answer.consumed) == (None, False)
    assert "id" not in AnswerRow.model_fields


def test_log_entry_and_the_rest_of_the_tables() -> None:
    entry = LogEntryRow(
        id=11,
        run_id="01J9Z0000000000000000000AB",
        node="implement",
        author=LogAuthor.agent,
        kind=LogKind.deliverable,
        text="added the read models",
        created=NOW,
    )
    submission = SubmissionRow(id=2, task_id=7, payload={"ok": True}, created=NOW)
    chunk = StreamChunkRow(
        id=5, task_id=7, seq=3, kind=ChunkKind.thought, text="…", created=NOW
    )
    event = EventRow(id=99, run_id=entry.run_id, name="task.started", created=NOW)

    assert entry.task_id is None
    assert submission.payload == {"ok": True}
    assert chunk.kind is ChunkKind.thought
    assert (event.task_id, event.data) == (None, {})


def test_rows_reject_a_value_outside_the_vocabulary() -> None:
    with pytest.raises(ValidationError):
        make_task(status="in-progress")
    with pytest.raises(ValidationError):
        LogEntryRow(
            id=11,
            run_id="01J9Z0000000000000000000AB",
            node="implement",
            author="robot",  # type: ignore[arg-type]
            text="…",
            created=NOW,
        )

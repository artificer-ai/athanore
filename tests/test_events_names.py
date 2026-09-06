"""Tests for :mod:`athanore.events` — the vocabulary and its payloads.

The vocabulary is a contract three other documents cite (03 §Event
vocabulary, 18, 10 §Realtime and caching), so these tests read 03's table
rather than a copy of it: a name added to the enum without a row, or a row
added without an enum member, fails here.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from athanore.events.model import Event
from athanore.events.names import (
    EPHEMERAL,
    PLUGIN_PREFIX,
    EventName,
    is_known,
    matches,
)
from athanore.events.payloads import (
    ENVELOPES,
    PAYLOADS,
    AgentStats,
    EventEnvelope,
    PluginEvent,
    RunCompleted,
    RunCreated,
    RunCreatedEvent,
    TaskCancelled,
    TaskStream,
    TaskStreamEvent,
)

DOC = Path(__file__).resolve().parents[1] / "docs" / "v1" / "03-domain-model.md"
ENVELOPE = TypeAdapter(EventEnvelope)
CREATED = datetime(2026, 9, 5, 14, 2, 11, 482000, tzinfo=UTC)


def _documented_names() -> list[str]:
    """Every event name in 03 §Event vocabulary, in the table's order.

    The plugin row names a template (``plugin.<wf>.<name>``), not an event,
    and is skipped: it is :func:`is_known`'s business, not the enum's.
    """
    section = DOC.read_text().split("## Event vocabulary", 1)[1].split("\n## ", 1)[0]
    names: list[str] = []
    for line in section.splitlines():
        if not line.startswith("|") or line.startswith("|---") or "| Event |" in line:
            continue
        cell = line.split("|")[1]
        names.extend(n for n in re.findall(r"`([^`]+)`", cell) if "<" not in n)
    return names


# --------------------------------------------------------------------------
# The vocabulary
# --------------------------------------------------------------------------


def test_the_enum_is_exactly_the_table_in_03() -> None:
    documented = _documented_names()
    assert documented, "03 §Event vocabulary parsed to nothing"
    assert [member.value for member in EventName] == documented


def test_every_name_is_subject_verb() -> None:
    for member in EventName:
        subject, _, verb = member.value.partition(".")
        assert verb, f"{member.value} is not subject.verb"
        assert "." not in verb, f"{member.value} has more than two segments"
        assert re.fullmatch(r"[a-z]+", subject), member.value
        assert re.fullmatch(r"[a-z][a-z_]*", verb), member.value


def test_member_names_mirror_their_values() -> None:
    for member in EventName:
        assert member.name == member.value.replace(".", "_")


def test_the_enum_is_a_string_enum() -> None:
    assert EventName.task_done == "task.done"
    assert f"{EventName.task_done}" == "task.done"


def test_only_task_stream_is_ephemeral() -> None:
    assert EPHEMERAL == {EventName.task_stream}


# --------------------------------------------------------------------------
# is_known
# --------------------------------------------------------------------------


def test_every_member_is_known() -> None:
    for member in EventName:
        assert is_known(member.value)


def test_plugin_names_are_known() -> None:
    assert PLUGIN_PREFIX == "plugin."
    assert is_known("plugin.gamedev.word")
    assert is_known("plugin.gamedev.word_counted")


@pytest.mark.parametrize(
    "name",
    [
        "plugin.x",  # two segments: no event name
        "plugin.",
        "plugin.gamedev.word.extra",  # four: the name segment is an identifier
        "plugin.game-dev.word",
        "plugin.gamedev.2word",
        "run.invented",
        "run.created ",
        "Run.created",
        "",
    ],
)
def test_unknown_names(name: str) -> None:
    assert not is_known(name)


# --------------------------------------------------------------------------
# matches
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("pattern", "name", "expected"),
    [
        ("task.*", "task.stream", True),
        ("run.*", "run.a.b", False),
        ("run.*", "run.created", True),
        ("*", "run.created", False),
        ("*.*", "run.created", True),
        ("run.created", "run.created", True),
        ("run.created", "run.completed", False),
        ("task.*", "run.created", False),
        ("plugin.*", "plugin.gamedev.word", False),
        ("plugin.*.*", "plugin.gamedev.word", True),
        ("plugin.gamedev.*", "plugin.other.word", False),
        ("task.d*", "task.done", True),
    ],
)
def test_matches(pattern: str, name: str, expected: bool) -> None:
    assert matches(pattern, name) is expected


def test_a_star_never_crosses_a_dot() -> None:
    """The one rule: a `*` is a segment, so `run.*` is not `run.**`."""
    for member in EventName:
        subject = member.value.split(".")[0]
        assert matches(f"{subject}.*", member.value)
    assert not matches("*", "plugin.gamedev.word")


# --------------------------------------------------------------------------
# Payloads
# --------------------------------------------------------------------------


def test_every_name_has_a_payload_model() -> None:
    """Read off the union, not a hand-written list.

    A name added to :class:`EventName` without a variant in
    :data:`EventEnvelope` has no entry in either mapping and fails here.
    """
    assert set(ENVELOPES) == set(EventName)
    assert set(PAYLOADS) == set(EventName)
    assert len({id(model) for model in PAYLOADS.values()}) == len(EventName)
    for name, envelope in ENVELOPES.items():
        assert envelope.model_fields["name"].default == name
        assert issubclass(PAYLOADS[name], BaseModel)


def test_every_name_routes_to_its_own_variant() -> None:
    """Validation picks the variant by name, for every name in the enum.

    An empty ``data`` is invalid for most payloads; what is asserted is
    where the union sent it, which the error's ``loc`` carries.
    """
    for name in EventName:
        payload = {"name": name.value, "created": CREATED, "data": {}}
        try:
            event = ENVELOPE.validate_python(payload)
        except ValidationError as exc:
            for error in exc.errors():
                assert error["loc"][0] == name.value
        else:
            assert type(event) is ENVELOPES[name]


def test_an_unknown_name_has_no_variant() -> None:
    with pytest.raises(ValidationError) as caught:
        ENVELOPE.validate_python(
            {"name": "run.invented", "created": CREATED, "data": {}}
        )
    assert caught.value.errors()[0]["type"] == "union_tag_invalid"


def test_plugin_events_fall_through_to_plugin_event() -> None:
    event = ENVELOPE.validate_python(
        {
            "name": "plugin.gamedev.word",
            "run_id": "01J",
            "created": CREATED,
            "data": {"word": "athanor", "count": 3},
        }
    )
    assert type(event) is PluginEvent
    assert event.data == {"word": "athanor", "count": 3}


def test_a_plugin_event_needs_a_plugin_name() -> None:
    with pytest.raises(ValidationError):
        PluginEvent(name="gamedev.word", created=CREATED, data={})


def test_optional_fields_are_absent_not_null() -> None:
    """18: a field marked `?` is omitted, never `null`-filled."""
    stats = AgentStats(node="qa", attempt=1, status="ok", duration_s=1.5)
    assert stats.model_dump() == {
        "node": "qa",
        "attempt": 1,
        "status": "ok",
        "duration_s": 1.5,
    }


def test_a_required_field_keeps_its_null() -> None:
    """A run whose last node returned `None` completed with that value."""
    completed = RunCompleted(node="qa", task_id=7, output=None, terminal_tasks=[7])
    assert completed.model_dump()["output"] is None


def test_the_envelope_omits_what_it_does_not_have() -> None:
    ephemeral = TaskStreamEvent(
        run_id="01J", task_id=7, created=CREATED, data=TaskStream(seq_from=4, seq_to=9)
    )
    dumped = ephemeral.model_dump(mode="json")
    assert "id" not in dumped
    assert dumped == {
        "run_id": "01J",
        "task_id": 7,
        "created": "2026-09-05T14:02:11.482000Z",
        "name": "task.stream",
        "data": {"seq_from": 4, "seq_to": 9},
    }


def test_from_is_spelled_from_on_the_wire() -> None:
    """`from` is a Python keyword; 18 fixes the wire name regardless."""
    cancelled = TaskCancelled(node="qa", from_="in_progress", reason="cancel")
    assert cancelled.model_dump() == {
        "node": "qa",
        "from": "in_progress",
        "reason": "cancel",
    }
    assert (
        TaskCancelled.model_validate(
            {"node": "qa", "from": "in_progress", "reason": "cancel"}
        )
        == cancelled
    )


def test_a_payload_refuses_a_field_18_does_not_name() -> None:
    with pytest.raises(ValidationError):
        RunCompleted(node="qa", task_id=7, output=1, terminal_tasks=[7], elapsed=3)  # type: ignore[call-arg]


def test_an_envelope_round_trips() -> None:
    event = RunCreatedEvent(
        id=1,
        run_id="01J",
        created=CREATED,
        data=RunCreated(workflow="v1_feature", title="T009", position=3),
    )
    assert ENVELOPE.validate_json(ENVELOPE.dump_json(event)) == event


# --------------------------------------------------------------------------
# The stored model
# --------------------------------------------------------------------------


def test_the_event_model_is_the_stored_row() -> None:
    event = Event(
        id=4821,
        run_id="01J",
        task_id=17,
        name=EventName.task_done,
        data={"node": "qa", "attempt": 1, "transitions": [], "terminal": True},
        created=CREATED,
    )
    assert event.name == "task.done"
    assert event.model_dump(mode="json")["created"] == "2026-09-05T14:02:11.482000Z"


def test_an_unstored_event_has_no_id() -> None:
    event = Event(
        name=EventName.engine_stopping, data={"task_ids": []}, created=CREATED
    )
    assert event.id is None
    assert event.run_id is None
    assert event.task_id is None

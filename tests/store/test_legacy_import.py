"""The v0 importer (07 §Importing a v0 database).

`tests/fixtures/v0/mvp_small.sqlite3` is a committed MVP database written
by `scripts/make_v0_fixture.py`: two runs, tasks in every v0 status, a
work log carrying both inferred kinds, the request channel including the
pre-``requests`` message kinds, and the event kinds the mapping table
renames. These tests import it and check the mapping table row by row,
that a second import writes nothing, and that the source file is not
touched.

The suite runs on both backends (``db_url``): the importer writes Core
statements against :mod:`athanore.store.tables`, so PostgreSQL is not a
different code path, but it is the only place the JSON columns and the
partial unique index on ``requests`` are exercised as ``JSONB`` and a
real partial index.
"""

from __future__ import annotations

import asyncio
import hashlib
import sqlite3
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Table, select
from sqlalchemy.ext.asyncio import AsyncEngine

from athanore.events.names import EventName
from athanore.store.engine import make_engine
from athanore.store.legacy import EVENT_NAMES, ImportReport, import_v0
from athanore.store.tables import (
    answers,
    events,
    log_entries,
    requests,
    runs,
    stream_chunks,
    submissions,
    tasks,
)

#: The committed fixture, read where it lies: the importer opens it
#: ``mode=ro``, so a test that dirtied the checkout would be the bug.
FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "v0"
    / "mvp_small.sqlite3"
)

#: The two run ids `scripts/make_v0_fixture.py` writes.
DONE_RUN = "0a1b2c3d4e5f"
QUEUED_RUN = "1a2b3c4d5e6f"

#: What one import of the fixture produces, per table. Every number is a
#: row of the mapping table: five tasks in the finished run and one in the
#: queued one; four of the nine messages are requests (the fifth names no
#: task) and three are answers (the fourth has no request to key on); five
#: transcript segments from two ``agent_progress`` flushes; sixteen of the
#: twenty-four events survive the rename.
EXPECTED = ImportReport(
    runs=2,
    tasks=6,
    submissions=2,
    log_entries=6,
    requests=4,
    answers=3,
    stream_chunks=5,
    events=16,
    skipped_runs=(),
    dropped_requests=1,
    dropped_answers=1,
    dropped_events=6,
)

#: Every table the importer writes, in the order a row set is compared.
IMPORTED_TABLES: tuple[Table, ...] = (
    runs,
    tasks,
    submissions,
    log_entries,
    requests,
    answers,
    stream_chunks,
    events,
)


def digest(path: Path) -> str:
    """The SHA-256 of a file's bytes."""

    return hashlib.sha256(path.read_bytes()).hexdigest()


async def rows_of(engine: AsyncEngine, table: Table) -> list[dict[str, Any]]:
    """Every row of ``table``, in a deterministic order."""

    order = [table.c.id] if "id" in table.c else [table.c.request_id]
    async with engine.connect() as conn:
        result = await conn.execute(select(table).order_by(*order))
        return [dict(mapping) for mapping in result.mappings()]


async def snapshot(engine: AsyncEngine) -> dict[str, list[dict[str, Any]]]:
    """The whole destination, table by table."""

    return {table.name: await rows_of(engine, table) for table in IMPORTED_TABLES}


@pytest.fixture
async def imported(db_url: str) -> AsyncIterator[tuple[ImportReport, AsyncEngine]]:
    """The fixture imported once, and an engine on the result."""

    report = await import_v0(FIXTURE, db_url)
    engine = make_engine(db_url)
    try:
        yield report, engine
    finally:
        await engine.dispose()


async def test_the_fixture_is_committed_and_small() -> None:
    """It travels with the suite; nothing regenerates it in CI."""

    assert FIXTURE.is_file()
    assert FIXTURE.stat().st_size < 200_000


async def test_row_counts_match_the_fixture(
    imported: tuple[ImportReport, AsyncEngine],
) -> None:
    """Every table holds what the mapping table says it should."""

    report, engine = imported
    assert report == EXPECTED
    counted = {
        table.name: len(await rows_of(engine, table)) for table in IMPORTED_TABLES
    }
    assert counted == {
        "runs": EXPECTED.runs,
        "tasks": EXPECTED.tasks,
        "submissions": EXPECTED.submissions,
        "log_entries": EXPECTED.log_entries,
        "requests": EXPECTED.requests,
        "answers": EXPECTED.answers,
        "stream_chunks": EXPECTED.stream_chunks,
        "events": EXPECTED.events,
    }


async def test_runs_keep_their_id_and_take_priority_as_position(
    imported: tuple[ImportReport, AsyncEngine],
) -> None:
    """`runs.id` is verbatim and `runs.priority` becomes `position`."""

    _, engine = imported
    by_id = {row["id"]: row for row in await rows_of(engine, runs)}
    assert set(by_id) == {DONE_RUN, QUEUED_RUN}
    assert by_id[DONE_RUN]["position"] == 0
    assert by_id[QUEUED_RUN]["position"] == 1


async def test_running_with_no_started_task_becomes_queued(
    imported: tuple[ImportReport, AsyncEngine],
) -> None:
    """The run that never dispatched anything is `queued`, not `running`."""

    _, engine = imported
    by_id = {row["id"]: row for row in await rows_of(engine, runs)}
    assert by_id[QUEUED_RUN]["status"] == "queued"
    assert by_id[QUEUED_RUN]["finished"] is None
    # The other run kept the terminal status it had, and its `finished`
    # is the last timestamp its own rows carry.
    assert by_id[DONE_RUN]["status"] == "completed"
    finished = [
        row["finished"]
        for row in await rows_of(engine, tasks)
        if row["run_id"] == DONE_RUN and row["finished"] is not None
    ]
    assert by_id[DONE_RUN]["finished"] == max(finished)


async def test_every_v0_task_status_survives(
    imported: tuple[ImportReport, AsyncEngine],
) -> None:
    """The fixture has one task per v0 status and each keeps it."""

    _, engine = imported
    statuses = sorted(row["status"] for row in await rows_of(engine, tasks))
    assert statuses == [
        "cancelled",
        "dead_letter",
        "done",
        "failed",
        "in_progress",
        "ready",
    ]


async def test_only_finished_tasks_keep_a_token_hash(
    imported: tuple[ImportReport, AsyncEngine],
) -> None:
    """07: finished tasks get `sha256(token)`, everything else `NULL`.

    A `ready` or `in_progress` row is still claimable, and the claim mints
    a token of its own; carrying the MVP's clear-text one over in any form
    would be a live credential surviving the import (12 §Task tokens).
    """

    _, engine = imported
    rows = await rows_of(engine, tasks)
    hashed = {row["node"]: row["token_hash"] for row in rows}
    assert hashed["plan"] == hashlib.sha256(b"tok-plan-1").hexdigest()
    assert hashed["review"] == hashlib.sha256(b"tok-review-1").hexdigest()
    assert hashed["qa"] is None  # in_progress
    assert hashed["prepare"] is None  # ready
    assert all(row["token_hash"] is None for row in rows if row["status"] == "ready")


async def test_no_clear_text_token_reaches_the_destination(
    sqlite_url: str,
) -> None:
    """Not in a column, and not anywhere in the file either."""

    await import_v0(FIXTURE, sqlite_url)
    path = Path(sqlite_url.split("///", 1)[1])
    blob = await asyncio.to_thread(path.read_bytes)
    assert b"tok-plan-1" not in blob
    assert b"tok-qa-1" not in blob


async def test_log_entries_infer_their_kind(
    imported: tuple[ImportReport, AsyncEngine],
) -> None:
    """`[stats]` is a stats entry, the engine's retry line is a failure."""

    _, engine = imported
    rows = await rows_of(engine, log_entries)
    kinds = [(row["author"], row["kind"]) for row in rows]
    assert kinds == [
        ("agent", None),
        ("engine", "stats"),
        ("engine", "failure"),
        ("user", None),
        # The MVP's task API let an agent name any author; v1's enum has
        # three, so an unknown one lands on the MVP's own default.
        ("agent", None),
        ("user", None),
    ]
    # v0's `log` table has no task column, so nothing is attributed.
    assert all(row["task_id"] is None for row in rows)


async def test_messages_split_into_requests_and_answers(
    imported: tuple[ImportReport, AsyncEngine],
) -> None:
    """Including the pre-`requests` kinds the MVP migrated in place."""

    _, engine = imported
    shapes = [
        (row["prompt"], row["mode"], row["source"], row["kind"])
        for row in await rows_of(engine, requests)
    ]
    assert shapes == [
        ("Which approach?", "options", "node", "question"),
        # legacy `permission`: options + agent, and v1's `kind` inferred
        ("permission: write file", "options", "agent", "permission"),
        # legacy `question`: text + node
        ("Proceed?", "text", "node", "question"),
        ("the agent has a question", "form", "agent", "elicitation"),
    ]
    # v0 numbered no request, so none is claimed to have an ordinal.
    assert all(row["ordinal"] is None for row in await rows_of(engine, requests))

    answered = await rows_of(engine, answers)
    assert [(row["option_id"], row["value"], row["consumed"]) for row in answered] == [
        ("small", None, True),
        # the legacy `decision`
        ("allow_once", None, True),
        # the legacy `reply`, whose text is its value
        (None, "yes, proceed", False),
    ]


async def test_a_request_with_no_task_is_counted_not_written(
    imported: tuple[ImportReport, AsyncEngine],
) -> None:
    """`requests.task_id` is NOT NULL; the report says one was dropped."""

    report, engine = imported
    assert report.dropped_requests == 1
    assert report.dropped_answers == 1
    prompts = {row["prompt"] for row in await rows_of(engine, requests)}
    assert "Anything else?" not in prompts


async def test_agent_progress_becomes_the_transcript(
    imported: tuple[ImportReport, AsyncEngine],
) -> None:
    """One chunk per segment, numbered from 1, `> tool:` lines apart."""

    _, engine = imported
    chunks = await rows_of(engine, stream_chunks)
    assert [row["seq"] for row in chunks] == [1, 2, 3, 4, 5]
    assert [row["kind"] for row in chunks] == [
        "text",
        "tool_call",
        "text",
        "tool_call",
        "text",
    ]
    assert len({row["task_id"] for row in chunks}) == 1
    assert chunks[0]["text"] == "Reading the plan."


async def test_run_stats_fills_both_places(
    imported: tuple[ImportReport, AsyncEngine],
) -> None:
    """An `agent.stats` event and the task's `stats` column."""

    _, engine = imported
    stats = [row["stats"] for row in await rows_of(engine, tasks) if row["stats"]]
    assert len(stats) == 1
    assert stats[0]["node"] == "plan"
    assert stats[0]["total_tokens"] == 13610

    emitted = [
        row for row in await rows_of(engine, events) if row["name"] == "agent.stats"
    ]
    assert len(emitted) == 1
    # 18: the stats entry of 05 verbatim.
    assert emitted[0]["data"] == stats[0]


async def test_transition_folds_into_task_enqueued(
    imported: tuple[ImportReport, AsyncEngine],
) -> None:
    """03 folded the MVP's `transition` into `task.enqueued`."""

    _, engine = imported
    enqueued = [
        row for row in await rows_of(engine, events) if row["name"] == "task.enqueued"
    ]
    reasons = [row["data"]["reason"] for row in enqueued]
    assert reasons == ["transition", "retry", "rerun", "manual_retry"]
    first = enqueued[0]
    assert first["data"]["node"] == "build"
    assert first["data"]["payload_present"] is True
    assert first["data"]["branch"] == []


async def test_events_are_renamed_onto_the_vocabulary(
    imported: tuple[ImportReport, AsyncEngine],
) -> None:
    """Every written event carries a name from 03, and its ids are v1's."""

    _, engine = imported
    written = await rows_of(engine, events)
    assert {row["name"] for row in written} <= {member.value for member in EventName}

    # The two events naming a request name the row the import created,
    # not the message id the MVP had.
    request_ids = {row["id"] for row in await rows_of(engine, requests)}
    for row in written:
        if row["name"] in ("request.opened", "request.answered"):
            assert row["data"]["request_id"] in request_ids


async def test_unmappable_event_kinds_are_counted(
    imported: tuple[ImportReport, AsyncEngine],
) -> None:
    """18 fixes a required payload; a v0 row that lacks it is not written.

    The fixture carries one of each: `run_completed` (no landing task, no
    terminal branches), `run_reordered` (no previous position),
    `task_status_set` (no status it came from), `submission` (no accepted
    row), `log` (no entry id), and an event naming no run at all.
    """

    report, engine = imported
    assert report.dropped_events == 6
    names = {row["name"] for row in await rows_of(engine, events)}
    assert "run.completed" not in names
    assert "run.reordered" not in names
    assert "task.status_set" not in names
    assert "submission.accepted" not in names
    assert "log.appended" not in names


async def test_event_names_are_the_vocabulary() -> None:
    """The store spells the names itself (02 §Layering); they must match."""

    assert set(EVENT_NAMES.values()) <= {member.value for member in EventName}


async def test_a_second_import_changes_nothing(db_url: str) -> None:
    """Idempotent: the run ids are already there, so nothing is written."""

    first = await import_v0(FIXTURE, db_url)
    engine = make_engine(db_url)
    try:
        before = await snapshot(engine)
        second = await import_v0(FIXTURE, db_url)
        after = await snapshot(engine)
    finally:
        await engine.dispose()

    assert first.skipped_runs == ()
    assert second.skipped_runs == (DONE_RUN, QUEUED_RUN)
    assert second.runs == second.tasks == second.events == 0
    assert after == before


async def test_the_source_is_never_written() -> None:
    """Hash the fixture before and after, and leave no journal beside it."""

    before = await asyncio.to_thread(digest, FIXTURE)
    sidecars = [FIXTURE.with_name(FIXTURE.name + suffix) for suffix in ("-wal", "-shm")]

    with tempfile.TemporaryDirectory() as tmp:
        await import_v0(FIXTURE, f"sqlite+aiosqlite:///{tmp}/v1.db")

    assert await asyncio.to_thread(digest, FIXTURE) == before
    assert not any(path.exists() for path in sidecars)


async def test_a_database_that_is_not_v0_is_refused(
    tmp_path: Path, db_url: str
) -> None:
    """A missing file and an empty one both say so rather than importing."""

    with pytest.raises(FileNotFoundError):
        await import_v0(tmp_path / "nothing.sqlite3", db_url)

    empty = tmp_path / "empty.sqlite3"
    sqlite3.connect(empty).close()
    with pytest.raises(ValueError, match="not a v0 athanore database"):
        await import_v0(empty, db_url)

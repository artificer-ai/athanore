"""Tests for :mod:`athanore.store.tables` and :mod:`athanore.store.engine`.

Nothing queries anything yet, so what is worth asserting is the shape of
the schema and the two properties SQLite does not give for free: the
pragmas of 07 §Concurrency, and the foreign keys they switch on. A
cascade that is never enforced looks exactly like one that is until a run
is deleted, which is why the enforcement is tested with a violation
rather than by reading the DDL.

The database is a temporary **file**. WAL is not available to
``:memory:``, so an in-memory database would report a journal mode that
production never runs with.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import String, Table, UniqueConstraint, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from athanore.store.engine import SQLITE_PRAGMAS, is_sqlite, make_engine
from athanore.store.tables import (
    answers,
    events,
    join_arrivals,
    log_entries,
    metadata,
    requests,
    runs,
    stream_chunks,
    submissions,
    tasks,
)

NOW = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    return f"sqlite+aiosqlite:///{tmp_path / 'athanore.db'}"


@pytest.fixture
async def engine(db_url: str) -> AsyncIterator[AsyncEngine]:
    """A migrated-by-``create_all`` database on a temporary file.

    T012 owns the migration; a test does not need one to exercise the
    metadata it is generated from.
    """

    eng = make_engine(db_url)
    async with eng.begin() as conn:
        await conn.run_sync(metadata.create_all)
    try:
        yield eng
    finally:
        await eng.dispose()


async def _insert_run(engine: AsyncEngine, run_id: str = "01JRUN") -> str:
    async with engine.begin() as conn:
        await conn.execute(
            runs.insert().values(
                id=run_id,
                workflow="demo",
                status="queued",
                title="a run",
                description="",
                position=1,
                created=NOW,
                updated=NOW,
            )
        )
    return run_id


async def _insert_task(engine: AsyncEngine, run_id: str, node: str = "start") -> int:
    async with engine.begin() as conn:
        result = await conn.execute(
            tasks.insert().values(
                run_id=run_id,
                node=node,
                attempt=1,
                status="ready",
                priority=0,
                created=NOW,
            )
        )
    primary_key = result.inserted_primary_key
    assert primary_key is not None
    task_id = primary_key[0]
    assert isinstance(task_id, int)
    return task_id


# --------------------------------------------------------------------------
# The shape of the schema (07 §Schema)
# --------------------------------------------------------------------------


def test_the_metadata_holds_the_nine_tables_of_07() -> None:
    assert set(metadata.tables) == {
        "runs",
        "tasks",
        "log_entries",
        "submissions",
        "stream_chunks",
        "requests",
        "answers",
        "join_arrivals",
        "events",
    }


@pytest.mark.parametrize(
    ("table", "expected"),
    [
        (runs, set()),
        (tasks, {"runs.id"}),
        (log_entries, {"runs.id", "tasks.id"}),
        (submissions, {"tasks.id"}),
        (stream_chunks, {"tasks.id"}),
        (requests, {"runs.id", "tasks.id"}),
        (answers, {"requests.id"}),
        (join_arrivals, {"runs.id", "tasks.id"}),
        # `events` is deliberately keyless: the outbox inserts its rows at
        # commit, so `run.deleted` — emitted by the transaction that
        # deletes the run — would violate a cascade on the way in.
        (events, set()),
    ],
    ids=lambda value: value.name if isinstance(value, Table) else str(value),
)
def test_foreign_keys_are_the_ones_07_marks(table: Table, expected: set[str]) -> None:
    assert {str(fk.target_fullname) for fk in table.foreign_keys} == expected


def test_every_foreign_key_cascades() -> None:
    for table in metadata.tables.values():
        for fk in table.foreign_keys:
            assert fk.ondelete == "CASCADE", f"{table.name}.{fk.parent.name}"


@pytest.mark.parametrize(
    ("table", "expected"),
    [
        (runs, {("position",), ("status",)}),
        (
            tasks,
            {("status", "run_id"), ("run_id", "id"), ("token_hash",)},
        ),
        (log_entries, {("run_id", "id")}),
        (submissions, {("task_id", "id")}),
        (stream_chunks, set()),
        (requests, {("run_id",), ("task_id", "ordinal")}),
        (answers, set()),
        (join_arrivals, set()),
        (events, {("run_id", "id"), ("name", "id")}),
    ],
    ids=lambda value: value.name if isinstance(value, Table) else str(value),
)
def test_indexes_are_the_ones_07_lists(
    table: Table, expected: set[tuple[str, ...]]
) -> None:
    assert {tuple(c.name for c in ix.columns) for ix in table.indexes} == expected


def test_unique_constraints_are_the_ones_07_lists() -> None:
    def uniques(table: Table) -> set[tuple[str, ...]]:
        return {
            tuple(c.name for c in constraint.columns)
            for constraint in table.constraints
            if isinstance(constraint, UniqueConstraint)
        }

    assert uniques(stream_chunks) == {("task_id", "seq")}
    assert uniques(join_arrivals) == {("run_id", "join_node", "fanout_task", "index")}
    # The request pair is a *partial* index, not a constraint: many rows
    # hold NULL.
    assert uniques(requests) == set()


def test_constraint_names_are_deterministic() -> None:
    """The naming convention applies, so T012's migration can name them.

    An unnamed constraint is named by the backend otherwise, differently
    on each, and Alembic's comparison has nothing stable to match.
    """

    fk = next(iter(tasks.foreign_keys)).constraint
    assert fk is not None
    assert fk.name == "fk_tasks_run_id_runs"
    assert tasks.primary_key.name == "pk_tasks"
    unique = next(
        c for c in stream_chunks.constraints if isinstance(c, UniqueConstraint)
    )
    assert unique.name == "uq_stream_chunks_task_id_seq"


def test_only_the_two_columns_07_marks_carry_a_server_default() -> None:
    """07 §Schema gives a DEFAULT to `tasks.terminal` and `tasks.branch`
    and to nothing else, so the initial migration T012 autogenerates
    declares those two and no more (D83)."""

    marked = {
        f"{table.name}.{column.name}"
        for table in metadata.sorted_tables
        for column in table.columns
        if column.server_default is not None
    }
    assert marked == {"tasks.terminal", "tasks.branch"}


def test_the_token_hash_column_is_nullable_and_sized() -> None:
    """NULL while the task is `ready`; 64 characters of SHA-256 after the
    claim writes it (07 §Schema notes)."""

    column = tasks.c.token_hash
    assert column.nullable
    assert isinstance(column.type, String)
    assert column.type.length == 64


# --------------------------------------------------------------------------
# The engine (07 §Concurrency and SQLite settings)
# --------------------------------------------------------------------------


async def test_create_all_builds_every_table(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        names = await conn.run_sync(
            lambda sync_conn: sorted(
                row[0]
                for row in sync_conn.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            )
        )
    assert set(metadata.tables) <= set(names)


@pytest.mark.parametrize(
    ("pragma", "expected"),
    [
        ("journal_mode", "wal"),
        ("synchronous", 1),  # NORMAL
        ("busy_timeout", 5000),
        ("foreign_keys", 1),  # ON
    ],
)
async def test_each_pragma_reads_back(
    engine: AsyncEngine, pragma: str, expected: object
) -> None:
    async with engine.connect() as conn:
        result = await conn.exec_driver_sql(f"PRAGMA {pragma}")
        assert result.scalar_one() == expected


def test_the_pragmas_are_the_four_07_names() -> None:
    assert dict(SQLITE_PRAGMAS) == {
        "journal_mode": "WAL",
        "synchronous": "NORMAL",
        "busy_timeout": "5000",
        "foreign_keys": "ON",
    }


def test_is_sqlite(db_url: str) -> None:
    assert is_sqlite(make_engine(db_url))
    assert not is_sqlite(make_engine("postgresql+asyncpg://u:p@localhost/db"))


def test_an_in_memory_url_takes_no_pool_size() -> None:
    """SQLAlchemy gives ``:memory:`` a single-connection pool, which
    rejects ``pool_size``; ``make_engine`` must still build one."""

    assert is_sqlite(make_engine("sqlite+aiosqlite://"))
    assert is_sqlite(make_engine("sqlite+aiosqlite:///:memory:"))


# --------------------------------------------------------------------------
# The constraints that only exist at runtime
# --------------------------------------------------------------------------


async def test_a_task_with_an_unknown_run_is_rejected(engine: AsyncEngine) -> None:
    """The proof that `foreign_keys=ON` reached the connection."""

    with pytest.raises(IntegrityError):
        await _insert_task(engine, "01JNOSUCHRUN")


async def test_deleting_a_run_cascades(engine: AsyncEngine) -> None:
    run_id = await _insert_run(engine)
    await _insert_task(engine, run_id)
    async with engine.begin() as conn:
        await conn.execute(runs.delete().where(runs.c.id == run_id))
    async with engine.connect() as conn:
        remaining = (await conn.execute(select(tasks.c.id))).all()
    assert remaining == []


async def test_a_repeated_request_ordinal_is_rejected(engine: AsyncEngine) -> None:
    run_id = await _insert_run(engine)
    task_id = await _insert_task(engine, run_id)

    async def add(ordinal: int | None) -> None:
        async with engine.begin() as conn:
            await conn.execute(
                requests.insert().values(
                    run_id=run_id,
                    task_id=task_id,
                    ordinal=ordinal,
                    prompt="which?",
                    mode="options",
                    source="node",
                    kind="question",
                    created=NOW,
                )
            )

    await add(0)
    with pytest.raises(IntegrityError):
        await add(0)


async def test_many_requests_may_have_no_ordinal(engine: AsyncEngine) -> None:
    """The index is partial: an agent raises as many requests as it likes,
    and none of them is numbered (06 §Restart durability)."""

    run_id = await _insert_run(engine)
    task_id = await _insert_task(engine, run_id)
    async with engine.begin() as conn:
        for _ in range(3):
            await conn.execute(
                requests.insert().values(
                    run_id=run_id,
                    task_id=task_id,
                    ordinal=None,
                    prompt="may I?",
                    mode="options",
                    source="agent",
                    kind="permission",
                    created=NOW,
                )
            )
        count = (await conn.execute(select(requests.c.id))).all()
    assert len(count) == 3


async def test_a_repeated_stream_seq_is_rejected(engine: AsyncEngine) -> None:
    run_id = await _insert_run(engine)
    task_id = await _insert_task(engine, run_id)

    async def add(seq: int) -> None:
        async with engine.begin() as conn:
            await conn.execute(
                stream_chunks.insert().values(
                    task_id=task_id, seq=seq, kind="text", text="hi", created=NOW
                )
            )

    await add(0)
    with pytest.raises(IntegrityError):
        await add(0)


async def test_task_defaults_land(engine: AsyncEngine) -> None:
    """`terminal` and `branch` are the two columns 07 gives defaults, and
    a task is enqueued without either."""

    run_id = await _insert_run(engine)
    task_id = await _insert_task(engine, run_id)
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                select(tasks.c.terminal, tasks.c.branch, tasks.c.token_hash).where(
                    tasks.c.id == task_id
                )
            )
        ).one()
    assert row.terminal is False
    assert row.branch == []
    assert row.token_hash is None


async def test_events_take_no_run_and_survive_it(engine: AsyncEngine) -> None:
    """An event names a run by value, not by key, so the last event of a
    run can be written by the transaction that deleted it."""

    run_id = await _insert_run(engine)
    async with engine.begin() as conn:
        await conn.execute(runs.delete().where(runs.c.id == run_id))
        await conn.execute(
            events.insert().values(
                run_id=run_id,
                name="run.deleted",
                data={"workflow": "demo", "title": "a run"},
                created=NOW,
            )
        )
    async with engine.connect() as conn:
        row = (await conn.execute(select(events.c.id, events.c.data))).one()
    assert row.id == 1
    assert row.data == {"workflow": "demo", "title": "a run"}


async def test_event_ids_are_never_reused(engine: AsyncEngine) -> None:
    """`events.id` is the SSE cursor, so retention deleting the newest
    rows must not hand their ids back out (D83)."""

    def row(name: str) -> dict[str, Any]:
        return {"name": name, "data": {}, "created": NOW}

    async with engine.begin() as conn:
        await conn.execute(events.insert(), [row("a"), row("b")])
        await conn.execute(events.delete().where(events.c.name == "b"))
        result = await conn.execute(events.insert().values(**row("c")))
    primary_key = result.inserted_primary_key
    assert primary_key is not None
    assert primary_key[0] == 3

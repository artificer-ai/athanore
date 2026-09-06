"""Tests for :mod:`athanore.store.migrate` and the ``0001`` migration.

The test that matters is :func:`test_upgrade_leaves_no_difference_from_the
_metadata`: it upgrades an empty file and asks Alembic to compare the
result with :data:`athanore.store.tables.metadata`. A migration that
drifts from the schema it is supposed to create is invisible until a
query fails in production, and hand-reading 250 lines of DDL against nine
``Table`` objects is not a check anybody repeats. It is also why the
metadata carries a naming convention (T011): an unnamed constraint is
named by the backend, and two backends name it differently, so the
comparison would be dialect-dependent.

The upgrade itself is backend-neutral and runs under the parametrised
``db_url`` of ``tests/store/conftest.py``, so the nightly job proves the
same migration builds the same schema on PostgreSQL. The tests whose
subject is the *file* — a question that must not create one, an MVP
database detected by its tables — take ``sqlite_url`` and ``sqlite_path``
instead and skip on the Postgres parameter. The SQLite database is a
temporary **file** throughout: a migration on ``:memory:`` would run
against a database that dies with its connection.
"""

from __future__ import annotations

import asyncio
import io
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, inspect

from athanore.store.engine import make_engine
from athanore.store.migrate import (
    SCRIPT_LOCATION,
    alembic_config,
    current,
    is_v0_database,
    upgrade,
)
from athanore.store.tables import metadata

#: The one revision this task ships.
REVISION = "0001"

T = TypeVar("T")


async def _read(db_url: str, read: Callable[[Connection], T]) -> T:
    """Run ``read`` on one connection to ``db_url`` and dispose the engine."""

    engine = make_engine(db_url)
    try:
        async with engine.connect() as connection:
            return await connection.run_sync(read)
    finally:
        await engine.dispose()


def _make_v0_database(path: Path) -> None:
    """A database shaped like the MVP's: a ``runs`` table, no Alembic.

    T018 commits the real fixture, built by the MVP's own ``Store``. Three
    of its tables are enough to exercise the predicate, and an inline stub
    tests it now where an ``xfail`` would test nothing.
    """

    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE runs (
                id TEXT PRIMARY KEY,
                workflow TEXT NOT NULL,
                status TEXT NOT NULL,
                priority INTEGER NOT NULL
            );
            CREATE TABLE tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                node TEXT NOT NULL,
                token TEXT
            );
            CREATE TABLE log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                text TEXT NOT NULL
            );
            INSERT INTO runs VALUES ('deadbeef', 'demo', 'completed', 0);
            """
        )
        connection.commit()
    finally:
        connection.close()


async def test_upgrade_leaves_no_difference_from_the_metadata(db_url: str) -> None:
    """The migration builds exactly what ``tables.metadata`` describes."""

    await upgrade(db_url)

    def diff(connection: Connection) -> list[object]:
        context = MigrationContext.configure(
            connection, opts={"target_metadata": metadata}
        )
        return list(compare_metadata(context, metadata))

    assert await _read(db_url, diff) == []


async def test_upgrade_creates_the_tables_of_the_schema(db_url: str) -> None:
    await upgrade(db_url)

    def table_names(connection: Connection) -> set[str]:
        return set(inspect(connection).get_table_names())

    names = await _read(db_url, table_names)
    assert set(metadata.tables) <= names
    assert "alembic_version" in names


async def test_current_is_the_one_revision_after_an_upgrade(db_url: str) -> None:
    await upgrade(db_url)

    assert await current(db_url) == REVISION


async def test_current_is_none_before_an_upgrade(
    sqlite_url: str, sqlite_path: Path
) -> None:
    """An empty file, and an absent one, are both unmigrated."""

    assert await current(sqlite_url) is None

    await asyncio.to_thread(sqlite_path.touch)
    assert await current(sqlite_url) is None


async def test_asking_about_an_absent_database_does_not_create_one(
    sqlite_url: str, sqlite_path: Path
) -> None:
    """The predicates are asked before anything decided to create a file.

    SQLite makes the file on connect, so a question that opened a
    connection would answer "not a v0 database" and leave an empty one
    behind for the next question to find.
    """

    assert await is_v0_database(sqlite_url) is False
    assert await current(sqlite_url) is None
    assert not await asyncio.to_thread(sqlite_path.exists)


async def test_upgrade_is_idempotent(db_url: str) -> None:
    await upgrade(db_url)
    await upgrade(db_url)

    assert await current(db_url) == REVISION


async def test_upgrade_to_an_explicit_revision(db_url: str) -> None:
    await upgrade(db_url, REVISION)

    assert await current(db_url) == REVISION


async def test_is_v0_database_for_a_v0_shaped_file(
    sqlite_url: str, sqlite_path: Path
) -> None:
    _make_v0_database(sqlite_path)

    assert await is_v0_database(sqlite_url) is True


async def test_a_migrated_database_is_not_v0(db_url: str) -> None:
    """v1 has both tables; the version table is what tells them apart."""

    await upgrade(db_url)

    assert await is_v0_database(db_url) is False


async def test_an_empty_database_is_not_v0(sqlite_url: str, sqlite_path: Path) -> None:
    sqlite3.connect(sqlite_path).close()

    assert await is_v0_database(sqlite_url) is False


def test_the_scripts_ship_inside_the_package() -> None:
    """``script_location`` resolves from the package, not from a checkout.

    A wheel has to be able to migrate its own database, so ``env.py`` and
    ``versions/`` are package data next to :mod:`athanore.store.migrate`.
    """

    assert SCRIPT_LOCATION.is_dir()
    assert (SCRIPT_LOCATION / "env.py").is_file()
    assert SCRIPT_LOCATION.is_relative_to(Path(__file__).resolve().parents[2])


def test_the_history_has_one_head(sqlite_url: str) -> None:
    """One linear history: a second head is a merge nobody asked for."""

    scripts = ScriptDirectory.from_config(alembic_config(sqlite_url))

    assert scripts.get_heads() == [REVISION]
    assert scripts.get_revision(REVISION).down_revision is None


async def test_offline_mode_emits_sql_without_touching_a_database(
    sqlite_url: str, sqlite_path: Path
) -> None:
    """``alembic upgrade head --sql``: the DDL, and no connection made."""

    config = alembic_config(sqlite_url)
    buffer = io.StringIO()
    config.output_buffer = buffer
    await asyncio.to_thread(command.upgrade, config, "head", sql=True)

    sql = buffer.getvalue()
    assert "CREATE TABLE runs" in sql
    assert "CREATE TABLE events" in sql
    assert not await asyncio.to_thread(sqlite_path.exists)


async def test_downgrade_removes_the_schema(db_url: str) -> None:
    """The reverse of ``0001``, which no test would otherwise run."""

    await upgrade(db_url)
    await asyncio.to_thread(command.downgrade, alembic_config(db_url), "base")

    def table_names(connection: Connection) -> set[str]:
        return set(inspect(connection).get_table_names())

    names = await _read(db_url, table_names)
    assert names - {"alembic_version"} == set()
    assert await current(db_url) is None

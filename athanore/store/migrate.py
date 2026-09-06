"""Alembic, driven programmatically.

07 §Migrations puts the schema's history in
``athanore/store/migrations/versions/`` and gives the operator
``athanore db upgrade`` / ``db current``; the server runs
``alembic upgrade head`` on start unless ``run_migrations`` is off. All
three go through this module, so there is one definition of where the
scripts live and one place that knows how to reach an async database.

Two shapes are load-bearing:

- :func:`alembic_config` builds the :class:`~alembic.config.Config` in
  code, with ``script_location`` resolved next to this package. An
  ``alembic.ini`` found in the current directory would be whatever
  directory the operator happened to be in; the package's own migrations
  are the only ones Athanore ever runs.
- :func:`upgrade` runs Alembic in a worker thread. ``env.py`` owns the
  async engine and calls :func:`asyncio.run` (07's engine settings are
  per-connection, so a migration must not open a raw one), and
  ``asyncio.run`` cannot be called from a thread that already has a
  running loop.

:func:`is_v0_database` is the detection half of 07 §Importing a v0
database: the MVP kept no ``alembic_version``, so a file that has the
MVP's ``runs`` table and no version table is a v0 database and must be
imported (T018), never migrated in place.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Connection, inspect
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection

from athanore.store.engine import make_engine

#: The migration environment, inside the package: ``env.py``,
#: ``script.py.mako`` and ``versions/``.
SCRIPT_LOCATION = Path(__file__).resolve().parent / "migrations"

#: The table Alembic stamps a database's revision in. Its absence is what
#: tells a v0 database from a v1 one.
VERSION_TABLE = "alembic_version"

#: The table every MVP database has (07 §Importing a v0 database).
V0_TABLE = "runs"


def alembic_config(db_url: str) -> Config:
    """The Alembic config for ``db_url``, pointed at the package's scripts.

    The URL travels in :attr:`Config.attributes` rather than as the
    ``sqlalchemy.url`` option: Alembic's config is a
    :mod:`configparser`, so a URL containing ``%`` — a password, an
    escaped path — would be read as an interpolation and either raise or
    silently change. ``env.py`` reads the attribute first.
    """

    config = Config()
    config.set_main_option("script_location", str(SCRIPT_LOCATION))
    config.attributes["db_url"] = db_url
    return config


async def upgrade(db_url: str, rev: str = "head") -> None:
    """Migrate ``db_url`` to ``rev``, creating the database if it is new.

    Runs in a worker thread: ``env.py`` drives the async engine with its
    own event loop, which cannot be started from inside this one.
    """

    await asyncio.to_thread(command.upgrade, alembic_config(db_url), rev)


async def current(db_url: str) -> str | None:
    """The revision ``db_url`` is stamped with, or ``None`` if unmigrated.

    ``None`` covers both a database that has never been migrated and one
    that does not exist yet.
    """

    if _is_missing_sqlite_file(db_url):
        return None
    async with _connect(db_url) as connection:
        return await connection.run_sync(_current_revision)


async def is_v0_database(db_url: str) -> bool:
    """Whether ``db_url`` is an MVP database awaiting ``db import-v0``.

    True when the database has the MVP's ``runs`` table and no
    ``alembic_version``: v0 created its schema in constructors and never
    stamped a revision (07 §Importing a v0 database). A v1 database has
    both tables; an empty or absent one has neither.
    """

    if _is_missing_sqlite_file(db_url):
        return False
    async with _connect(db_url) as connection:
        return await connection.run_sync(_looks_like_v0)


def _current_revision(connection: Connection) -> str | None:
    return MigrationContext.configure(connection).get_current_revision()


def _looks_like_v0(connection: Connection) -> bool:
    names = set(inspect(connection).get_table_names())
    return V0_TABLE in names and VERSION_TABLE not in names


@asynccontextmanager
async def _connect(db_url: str) -> AsyncGenerator[AsyncConnection, None]:
    """One connection to ``db_url``, with the engine disposed after it.

    Both readers are one-shot questions asked before the store exists, so
    they own their engine rather than borrowing one.
    """

    engine = make_engine(db_url)
    try:
        async with engine.connect() as connection:
            yield connection
    finally:
        await engine.dispose()


def _is_missing_sqlite_file(db_url: str) -> bool:
    """Whether ``db_url`` names a SQLite file that does not exist.

    SQLite creates the file on connect, so asking either question about a
    database that is not there would otherwise leave an empty one behind
    — and both are asked before anything has decided to create it.
    """

    url = make_url(db_url)
    if url.get_backend_name() != "sqlite":
        return False
    database = url.database
    if not database or database == ":memory:" or database.startswith("file:"):
        return False
    return not Path(database).exists()


__all__ = [
    "SCRIPT_LOCATION",
    "V0_TABLE",
    "VERSION_TABLE",
    "alembic_config",
    "current",
    "is_v0_database",
    "upgrade",
]

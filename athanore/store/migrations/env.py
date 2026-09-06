"""The Alembic environment, run by ``alembic`` for every migration.

It lives inside the package because a shipped wheel has to be able to
migrate its own database: ``script_location`` resolves next to this file,
not from a source checkout (07 §Migrations).

Two things here are not the template's defaults:

- the engine comes from :func:`athanore.store.engine.make_engine`, so a
  migration runs with the pragmas of 07 §Concurrency — notably
  ``foreign_keys=ON``, without which a later migration that rebuilds a
  table would silently drop the keys it copies;
- ``render_as_batch=True``, because SQLite cannot ``ALTER`` a column and
  Alembic has to rebuild the table instead. It costs nothing on the first
  migration and is the difference between a writable and an unwritable
  second one.

The database URL arrives in ``config.attributes["db_url"]``
(:func:`athanore.store.migrate.alembic_config`) rather than in the
``sqlalchemy.url`` option, because Alembic's config is a
:mod:`configparser` and a password containing ``%`` would be read as an
interpolation. The operator running the ``alembic`` command directly has
neither, so ``-x db_url=...`` and ``sqlalchemy.url`` are honoured too.
"""

from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy import Connection

from athanore.store.engine import make_engine
from athanore.store.tables import metadata

#: What ``--autogenerate`` compares a database against: the one
#: description of the schema (:mod:`athanore.store.tables`).
target_metadata = metadata

config = context.config


def _db_url() -> str:
    """The database to migrate, from the config Alembic was given."""

    url = (
        config.attributes.get("db_url")
        or context.get_x_argument(as_dictionary=True).get("db_url")
        or config.get_main_option("sqlalchemy.url")
    )
    if not url:
        raise RuntimeError(
            "no database URL: pass one as Config.attributes['db_url'] "
            "(athanore.store.migrate.alembic_config), as -x db_url=..., "
            "or as sqlalchemy.url in alembic.ini"
        )
    return str(url)


def run_migrations_offline() -> None:
    """Emit the migrations as SQL, without a database (``alembic --sql``)."""

    context.configure(
        url=_db_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    """Run the migrations on an open (synchronous-facing) connection."""

    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_async_migrations() -> None:
    """Open the async engine and hand a connection to Alembic."""

    engine = make_engine(_db_url())
    try:
        async with engine.begin() as connection:
            await connection.run_sync(_do_run_migrations)
    finally:
        await engine.dispose()


def run_migrations_online() -> None:
    """Run the migrations against a live database."""

    asyncio.run(_run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

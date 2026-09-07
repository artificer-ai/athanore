"""``athanore db``: the verbs that repair or copy an installation (11).

Four operations on the database itself, and the only place in the CLI
that opens one rather than asking a server about it. That is deliberate:
each is a thing you do when the server is *not* running, or when it will
not start.

- ``upgrade`` / ``current`` are Alembic, driven through
  :mod:`athanore.store.migrate` so the scripts are always the package's
  own (07 §Migrations). The server runs the same ``upgrade`` on start;
  this is how an operator runs it themselves, and how a database gets
  migrated without serving anything. ``upgrade`` makes the server's v0
  refusal as well, because this verb is the one that would do the damage
  it exists to prevent.
- ``backup`` uses :meth:`sqlite3.Connection.backup`, which is the SQLite
  backup API: it takes a consistent copy of a live database, WAL and all,
  which copying the file with ``cp`` does not (07 §Backups). The
  destination is written ``0600``, because it is a copy of a file 12
  §Hygiene keeps at ``0600``.
- ``import-v0`` is the one-way door of 07 §Importing a v0 database. The
  MVP file is opened read-only and never written; the destination is
  migrated to head first, so importing into a path that does not exist
  yet is the ordinary case.

Every one of them names its database the same way: ``--db`` if it was
given, and otherwise ``settings.db_url``, which is the environment, then
``athanore.toml``, then ``{root_path}/athanore.db``. So ``athanore db
upgrade`` in a project directory migrates the database that ``athanore
serve`` in that directory would open, and neither has to be told which.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
from pathlib import Path
from typing import Annotated

import typer
from sqlalchemy.engine import make_url

from athanore.cli import Options, app
from athanore.cli.output import EXIT_API_ERROR, emit, fail
from athanore.settings import AthanoreSettings
from athanore.store import legacy, migrate

__all__ = ["backup", "current", "db_app", "import_v0", "resolve_db_url", "upgrade"]

db_app = typer.Typer(
    name="db",
    help="Migrate, copy, and import a database.",
    no_args_is_help=True,
)
app.add_typer(db_app, name="db")

#: The ``--db`` every subcommand takes, spelled once.
DbOption = Annotated[
    str | None,
    typer.Option(
        "--db",
        metavar="URL",
        help="The database to act on. Defaults to the configured one.",
    ),
]


def resolve_db_url(db: str | None) -> str:
    """``db`` if the operator named one, else the configured database."""

    if db is not None:
        return db
    settings = AthanoreSettings()
    url = settings.db_url
    if url is None:  # pragma: no cover - the settings validator computes it
        raise typer.BadParameter("no database is configured; pass --db.")
    return url


def _sqlite_file(db_url: str) -> Path:
    """The file ``db_url`` names, for the verbs that can only be SQLite.

    ``backup`` is the SQLite backup API and nothing else — PostgreSQL has
    its own tools and pretending otherwise would produce a file that is
    not a backup of anything (07 §Backups).
    """

    url = make_url(db_url)
    if url.get_backend_name() != "sqlite":
        fail(
            f"`db backup` copies a SQLite database, and {url.render_as_string()} "
            f"is {url.get_backend_name()}; use that server's own tools."
        )
        raise typer.Exit(EXIT_API_ERROR)
    database = url.database
    if not database or database == ":memory:":
        fail(f"{db_url} is an in-memory database; there is nothing to copy.")
        raise typer.Exit(EXIT_API_ERROR)
    path = Path(database)
    if not path.is_file():
        fail(f"{path} does not exist; there is no database to copy.")
        raise typer.Exit(EXIT_API_ERROR)
    return path


def _json(ctx: typer.Context) -> bool:
    """Whether the operator asked for JSON on the application's callback."""

    options = ctx.obj
    return options.json if isinstance(options, Options) else False


@db_app.command()
def upgrade(ctx: typer.Context, db: DbOption = None) -> None:
    """Migrate the database to the newest revision."""

    db_url = resolve_db_url(db)
    if asyncio.run(migrate.is_v0_database(db_url)):
        # The refusal `Server.start` makes, made here too, because this
        # verb is the one that would actually do the damage: Alembic
        # against an MVP file creates v1's tables beside the MVP's and
        # stamps a revision on a database that was never a v1 one, and
        # the history it holds is then readable by nothing (07 §Importing
        # a v0 database).
        fail(
            f"{db_url} is an athanore v0 database: it has the MVP's `runs` "
            f"table and no `alembic_version`. Migrating it in place would "
            f"strand its history in tables v1 does not read. Import it into "
            f"a fresh v1 database instead — the v0 file is opened read-only "
            f"and never modified: `athanore db import-v0 <the v0 file> --db "
            f"<a new database>`."
        )
        raise typer.Exit(EXIT_API_ERROR)
    asyncio.run(migrate.upgrade(db_url))
    revision = asyncio.run(migrate.current(db_url))
    emit({"db_url": db_url, "revision": revision}, json_flag=_json(ctx))


@db_app.command()
def current(ctx: typer.Context, db: DbOption = None) -> None:
    """Print the revision the database is stamped with."""

    db_url = resolve_db_url(db)
    revision = asyncio.run(migrate.current(db_url))
    # `None` is a database that has never been migrated, and it is
    # reported as the absence it is rather than as a revision called
    # "none" (02 §Real data only).
    emit({"db_url": db_url, "revision": revision}, json_flag=_json(ctx))


@db_app.command()
def backup(
    ctx: typer.Context,
    path: Annotated[
        Path,
        typer.Argument(help="Where to write the copy. Must not exist."),
    ],
    db: DbOption = None,
) -> None:
    """Copy a live SQLite database consistently (07 §Backups)."""

    db_url = resolve_db_url(db)
    source_path = _sqlite_file(db_url)
    destination = path.expanduser()
    if destination.exists():
        raise typer.BadParameter(
            f"{destination} already exists; a backup never overwrites one."
        )
    if not destination.parent.is_dir():
        raise typer.BadParameter(f"{destination.parent} is not a directory.")
    source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    try:
        target = sqlite3.connect(destination)
        try:
            source.backup(target)
        finally:
            target.close()
    except sqlite3.Error as exc:
        # A copy that failed half way is not a backup, and leaving the
        # file would leave something that looks like one.
        destination.unlink(missing_ok=True)
        fail(f"{source_path} could not be copied to {destination}: {exc}")
        raise typer.Exit(EXIT_API_ERROR) from exc
    finally:
        source.close()
    os.chmod(destination, 0o600)
    emit(
        {
            "source": str(source_path),
            "backup": str(destination),
            "bytes": destination.stat().st_size,
        },
        json_flag=_json(ctx),
    )


@db_app.command("import-v0")
def import_v0(
    ctx: typer.Context,
    source: Annotated[
        Path,
        typer.Argument(
            exists=True,
            dir_okay=False,
            readable=True,
            help="The MVP database to read. Opened read-only, never written.",
        ),
    ],
    db: DbOption = None,
) -> None:
    """Import an MVP database into a v1 one (07 §Importing a v0 database)."""

    db_url = resolve_db_url(db)
    try:
        report = asyncio.run(legacy.import_v0(source.expanduser(), db_url))
    except sqlite3.DatabaseError as exc:
        fail(f"{source} could not be read as an athanore v0 database: {exc}")
        raise typer.Exit(EXIT_API_ERROR) from exc
    emit(
        {"source": str(source), "db_url": db_url, **report._asdict()},
        json_flag=_json(ctx),
    )

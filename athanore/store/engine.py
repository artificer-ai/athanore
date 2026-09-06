"""The async engine factory.

One function makes the engine every part of the store uses, because the
SQLite settings of 07 §Concurrency are per *connection*, not per database:
a pool that opens a second connection without them is a connection with
foreign keys off and no busy timeout. Attaching them to the engine's
``connect`` event is the only place that cannot be forgotten.

``foreign_keys=ON`` is the load-bearing one. SQLite defaults it *off*, so
without this listener every cascade in :mod:`athanore.store.tables` is
decorative: a task could name a run that does not exist and deleting a run
would leave its tasks behind.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, event
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

# 07 §Concurrency and SQLite settings. WAL so a reader never blocks the
# writer; `synchronous=NORMAL` because losing the last transactions to a
# power cut is acceptable for a local tool and an fsync per commit is not;
# a busy timeout so a reader that meets the writer waits rather than
# raising; foreign keys because SQLite will not enforce them otherwise.
SQLITE_PRAGMAS: tuple[tuple[str, str], ...] = (
    ("journal_mode", "WAL"),
    ("synchronous", "NORMAL"),
    ("busy_timeout", "5000"),
    ("foreign_keys", "ON"),
)

# Small: the UnitOfWork serialises the one writer with an asyncio lock, so
# the pool exists for the readers (07 §Concurrency).
POOL_SIZE = 4


def _is_memory_sqlite(url: URL) -> bool:
    """Whether ``url`` names an in-memory SQLite database.

    SQLAlchemy gives those a pool that holds a single connection — the
    database dies with it — and that pool takes no ``pool_size``.
    """

    if url.get_backend_name() != "sqlite":
        return False
    database = url.database
    if database is None or database in ("", ":memory:"):
        return True
    return url.query.get("mode") == "memory"


def _set_sqlite_pragmas(dbapi_connection: Any, connection_record: Any) -> None:
    """Apply :data:`SQLITE_PRAGMAS` to one freshly opened connection.

    The DBAPI connection is aiosqlite's sync-facing adapter, so the
    cursor here is used synchronously; this is the listener SQLAlchemy
    documents for per-connection SQLite setup.
    """

    cursor = dbapi_connection.cursor()
    try:
        for pragma, value in SQLITE_PRAGMAS:
            cursor.execute(f"PRAGMA {pragma}={value}")
    finally:
        cursor.close()


def is_sqlite(engine: AsyncEngine | Engine) -> bool:
    """Whether ``engine`` speaks SQLite.

    The repositories ask because a handful of statements differ by
    dialect — ``GROUP_CONCAT`` against ``string_agg``, ``json_extract``
    against ``->>``, ``FOR UPDATE SKIP LOCKED`` where there is more than
    one writer (07 §Repositories).
    """

    return engine.dialect.name == "sqlite"


def make_engine(db_url: str) -> AsyncEngine:
    """The engine for ``db_url``, configured for the backend it names.

    SQLite gets the pragmas of 07; every backend gets a small pool. The
    engine is returned unconnected — SQLAlchemy connects lazily — so
    nothing here touches the filesystem.
    """

    url = make_url(db_url)
    kwargs: dict[str, Any] = {}
    if not _is_memory_sqlite(url):
        kwargs["pool_size"] = POOL_SIZE
    engine = create_async_engine(url, **kwargs)
    if is_sqlite(engine):
        event.listen(engine.sync_engine, "connect", _set_sqlite_pragmas)
    return engine


__all__ = ["POOL_SIZE", "SQLITE_PRAGMAS", "is_sqlite", "make_engine"]

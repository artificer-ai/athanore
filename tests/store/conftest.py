"""The backend matrix for the store suite.

13 §Pyramid runs the repositories against SQLite on a temporary file
always, and against PostgreSQL in a nightly job. This module is what
makes that one suite rather than two: :func:`db_url` is parametrised, so
every test that asks for a database is collected twice and the second
copy carries the ``postgres`` marker.

Three properties are deliberate:

- **The Postgres variants skip, they never error.** They skip when
  ``ATHANORE_TEST_PG_URL`` is unset, and they skip when it is set but
  nothing is listening — which is what the dev container looks like
  before ``docker compose --profile pg up -d postgres``. The probe runs
  once per session and its verdict is cached, so a suite with the profile
  down pays for one refused connection, not one per test.
- **Each test gets an empty database.** SQLite gets a fresh file under
  ``tmp_path``. PostgreSQL cannot, so the schema is dropped and recreated
  before each test — including ``alembic_version``, so a migration test
  starts from nothing the same way an empty file does.
- **A file, never ``:memory:``.** WAL is not available to an in-memory
  database, and a pool that holds one connection would hide the very
  thing :meth:`Store.read` exists to prove.

A test whose subject *is* SQLite — the pragmas of 07 §Concurrency, the
file that must not be created by a question — asks for :func:`sqlite_url`
instead and skips on the Postgres parameter.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from athanore.events.bus import EventBus
from athanore.store.engine import make_engine
from athanore.store.tables import metadata
from athanore.store.uow import Store

#: The environment variable the dev stack and the nightly job set to a
#: live PostgreSQL (T000; `compose.yaml`'s `pg` profile).
PG_URL_ENV = "ATHANORE_TEST_PG_URL"

#: One probe per URL per session: ``None`` once it answered, or the
#: reason it did not.
_PG_PROBE: dict[str, str | None] = {}


@pytest.fixture(
    params=[
        pytest.param("sqlite", id="sqlite"),
        pytest.param("postgres", id="postgres", marks=pytest.mark.postgres),
    ]
)
def backend(request: pytest.FixtureRequest) -> str:
    """Which backend this copy of the test runs against."""

    return str(request.param)


@pytest.fixture
def sqlite_path(tmp_path: Path) -> Path:
    """The file a SQLite database lives in for one test."""

    return tmp_path / "athanore.db"


@pytest.fixture
def sqlite_url(backend: str, sqlite_path: Path) -> str:
    """A SQLite URL, for tests whose subject is SQLite itself.

    Skips on the Postgres parameter rather than being collected only
    once: a suite that shows what it did not run is easier to trust than
    one that quietly ran less.
    """

    if backend != "sqlite":
        pytest.skip("this behaviour is SQLite's own")
    return f"sqlite+aiosqlite:///{sqlite_path}"


@pytest.fixture
async def db_url(backend: str, sqlite_path: Path) -> str:
    """An empty database on this parameter's backend."""

    if backend == "sqlite":
        return f"sqlite+aiosqlite:///{sqlite_path}"
    url = os.environ.get(PG_URL_ENV)
    if not url:
        pytest.skip(f"{PG_URL_ENV} is not set")
    await _require_postgres(url)
    await _empty_postgres(url)
    return url


@pytest.fixture
async def engine(db_url: str) -> AsyncIterator[AsyncEngine]:
    """The schema of :data:`athanore.store.tables.metadata`, created.

    T012 owns the migration; a repository test does not need one to
    exercise the metadata it is generated from.
    """

    eng = make_engine(db_url)
    async with eng.begin() as conn:
        await conn.run_sync(metadata.create_all)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def store(engine: AsyncEngine, bus: EventBus) -> Store:
    return Store(engine, bus)


async def _require_postgres(url: str) -> None:
    """Skip the test unless ``url`` answers; ask at most once per session."""

    if url not in _PG_PROBE:
        engine = make_engine(url)
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            _PG_PROBE[url] = None
        except Exception as exc:  # noqa: BLE001 - any failure is "not there"
            _PG_PROBE[url] = f"{type(exc).__name__}: {exc}"
        finally:
            await engine.dispose()
    reason = _PG_PROBE[url]
    if reason is not None:
        pytest.skip(
            f"no PostgreSQL at {PG_URL_ENV} "
            f"(`docker compose --profile pg up -d postgres`): {reason}"
        )


async def _empty_postgres(url: str) -> None:
    """Drop everything in the target schema, ``alembic_version`` included."""

    engine = make_engine(url)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
    finally:
        await engine.dispose()

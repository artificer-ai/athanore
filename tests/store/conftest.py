"""The database a store test runs against.

13 §Pyramid runs the repositories against SQLite on a temporary file
always, and against PostgreSQL in a nightly job; T014b parametrises this
module over both. Until then a store test gets a fresh SQLite file under
``tmp_path``.

**A file, never ``:memory:``.** WAL is not available to an in-memory
database, and a pool that holds one connection would hide the very thing
:meth:`Store.read` exists to prove.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from athanore.events.bus import EventBus
from athanore.store.engine import make_engine
from athanore.store.tables import metadata
from athanore.store.uow import Store


@pytest.fixture
def sqlite_path(tmp_path: Path) -> Path:
    """The file a SQLite database lives in for one test."""

    return tmp_path / "athanore.db"


@pytest.fixture
def sqlite_url(sqlite_path: Path) -> str:
    """A SQLite URL, for tests whose subject is SQLite itself."""

    return f"sqlite+aiosqlite:///{sqlite_path}"


@pytest.fixture
def db_url(sqlite_path: Path) -> str:
    """An empty database for one test."""

    return f"sqlite+aiosqlite:///{sqlite_path}"


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

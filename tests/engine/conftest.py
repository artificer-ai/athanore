"""A store for the engine suite.

The engine's subject is behaviour over the store, not the store's SQL, so
this suite runs against SQLite only — the backend matrix belongs to
``tests/store`` (13 §Pyramid). A file rather than ``:memory:``, for the
reason ``tests/store/conftest.py`` gives: WAL and a real pool are what the
services meet in production, and an in-memory database has neither.
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
def db_url(tmp_path: Path) -> str:
    """An empty SQLite database for one test."""

    return f"sqlite+aiosqlite:///{tmp_path / 'athanore.db'}"


@pytest.fixture
async def engine(db_url: str) -> AsyncIterator[AsyncEngine]:
    """The schema of :data:`athanore.store.tables.metadata`, created."""

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

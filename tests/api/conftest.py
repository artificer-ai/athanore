"""The application an API test drives, and the store behind it.

One `create_app()` with a real engine and a real store, spoken to over
ASGI with `httpx.ASGITransport` (13 §Pyramid): the routers are tested
through the stack they run in — the body cap, the error handlers, the
auth dependency — rather than by calling their functions.

The engine is registered on but **never started**: no dispatch loop, so a
run submitted here stays `queued` and nothing claims it out from under an
assertion. The suites that need work to actually run are the engine's
(`tests/engine`), where the subject is the loop rather than the wire.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from athanore.api.app import create_app
from athanore.engine import Engine
from athanore.events.bus import EventBus
from athanore.settings import AthanoreSettings
from athanore.store.engine import make_engine
from athanore.store.tables import metadata
from athanore.store.uow import Store


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    """An empty SQLite database for one test."""

    return f"sqlite+aiosqlite:///{tmp_path / 'athanore.db'}"


@pytest.fixture
async def sa_engine(db_url: str) -> AsyncIterator[AsyncEngine]:
    """The schema of :data:`athanore.store.tables.metadata`, created.

    Named for what it is — SQLAlchemy's engine — because `engine` in this
    suite is Athanore's, which is what the application is built with.
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
def store(sa_engine: AsyncEngine, bus: EventBus) -> Store:
    return Store(sa_engine, bus)


@pytest.fixture
def settings(tmp_path: Path, db_url: str) -> AthanoreSettings:
    """A plain loopback bind, pinned to this test's database.

    Every field the API reads is passed explicitly, so an `ATHANORE_*`
    variable in the shell that started the container cannot change what a
    test asserts. `root_path` matters most: without it
    `effective_operator_token` would read the developer's own token file.
    """

    return AthanoreSettings(
        root_path=tmp_path,
        db_url=db_url,
        public_url="http://127.0.0.1:4002",
        workers=1,
    )


@pytest.fixture
def engine(settings: AthanoreSettings, store: Store, bus: EventBus) -> Engine:
    """An engine with nothing registered and no loop running."""

    return Engine(settings, store, bus)


@pytest.fixture
def app(settings: AthanoreSettings, engine: Engine, store: Store) -> FastAPI:
    """The real application, built the way every host builds it."""

    return create_app(settings=settings, engine=engine, store=store)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """An HTTP client speaking ASGI to ``app``."""

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as http:
        yield http

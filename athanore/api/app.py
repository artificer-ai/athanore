"""The FastAPI application factory.

`create_app` is the one way an Athanore server is built: the CLI, the
programmatic `Server` host and the tests all call it, and its signature
is the published one (02 §Package layout).

What it assembles is the API's spine — the error shape of 08
§Conventions, the body cap of 08 §Sizes, the operator-token check that
refuses a configuration whose auth could never succeed (12 §Operator
token), and the application state every router reads its collaborators
from. The routers arrive one task at a time; the system router of 08
§System is the first of them.

The lifespan starts one thing and one thing only: the MCP endpoint's
session manager, which the application owns because the application
mounted it (08 §MCP). Starting the engine belongs to the host that owns
it (T031), not to the application it serves.

The OpenAPI document generated from this app is committed as
`tests/snapshots/openapi.json`, and the SPA's TypeScript client is
generated from that snapshot (02 §One wire contract). Every task that
adds a route regenerates both as part of its own definition of done.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from athanore.api import VERSION
from athanore.api.deps import check_operator_token
from athanore.api.errors import install_error_handlers
from athanore.api.mcp import mount as mount_mcp
from athanore.api.middleware import BodyLimitMiddleware
from athanore.api.routers import agent, requests, runs, system, tasks, workflows
from athanore.api.sse import router as sse_router
from athanore.engine import Engine
from athanore.settings import AthanoreSettings
from athanore.store.clock import now
from athanore.store.uow import Store

__all__ = ["VERSION", "create_app"]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """The application's startup and shutdown.

    One collaborator has a lifecycle the application owns: the MCP
    server's session manager, which holds the task group each request's
    server instance runs in and therefore serves nothing until it is
    entered (08 §MCP). Everything else — the engine, the store, the event
    bus — is started and stopped by whoever built it and handed it here
    (04 §Shutdown), because an application that started an engine it did
    not own would stop one out from under a host still using it.
    """

    async with app.state.mcp.run():
        yield


def create_app(
    settings: AthanoreSettings | None = None,
    engine: Engine | None = None,
    store: Store | None = None,
    plugins: Any = None,
) -> FastAPI:
    """Build the ASGI application.

    `settings` defaults to a freshly loaded :class:`AthanoreSettings`, so
    a bare `create_app()` is the server the environment describes.
    `plugins` is untyped only because the plugin registry does not exist
    yet; it becomes the registry in T049.

    Raises :class:`~athanore.api.deps.MissingOperatorToken` when the
    settings turn operator auth on without a token to check against —
    a non-loopback bind, or `require_token` — so the refusal belongs to
    the application every host builds rather than to one host's
    ``serve`` (12 §Operator token).

    The collaborators are put on `app.state` rather than closed over:
    dependencies reach them through `request.app.state`, which is what
    lets a router be a plain module-level `APIRouter` instead of a
    factory (08 §Endpoints).
    """

    settings = settings if settings is not None else AthanoreSettings()
    check_operator_token(settings)

    app = FastAPI(title="Athanore", version=VERSION, lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.store = store
    app.state.plugins = plugins
    # When this process came up. `/api/me` reports it and the SPA
    # refetches the plugin manifest whenever it changes (09).
    app.state.started_at = now()

    # Outermost of the application's own middleware: the body cap has to
    # run before anything reads a byte of the request (08 §Sizes).
    app.add_middleware(BodyLimitMiddleware, limit=settings.body_limit)
    install_error_handlers(app)
    app.include_router(system.router)
    app.include_router(workflows.router)
    app.include_router(runs.router)
    app.include_router(tasks.router)
    app.include_router(requests.router)
    app.include_router(agent.router)
    # Not under `routers/`: the stream is one endpoint and a generator,
    # and 02 §Package layout gives it its own module (`api/sse.py`).
    app.include_router(sse_router)
    # Last, and not a router: the same five capabilities as MCP tools,
    # on a mounted ASGI application with its own auth at the door (08
    # §MCP). The manager it returns is what `lifespan` runs.
    app.state.mcp = mount_mcp(app, settings)

    return app

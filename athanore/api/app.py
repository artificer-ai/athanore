"""The FastAPI application factory.

`create_app` is the one way an Athanore server is built: the CLI, the
programmatic `Server` host and the tests all call it, and its signature
is the published one (02 §Package layout).

What it assembles is the API's spine — the error shape of 08
§Conventions, the body cap of 08 §Sizes, and the application state every
router reads its collaborators from. The routers themselves arrive one
task at a time from T043 onward, and the lifespan is empty on purpose:
starting the engine belongs to the host that owns it (T031), not to the
application it serves.

The one route here is the unauthenticated `GET /api/health` of 08
§System. That is enough to freeze the wire contract: the OpenAPI
document generated from this app is committed as
`tests/snapshots/openapi.json`, and the SPA's TypeScript client is
generated from that snapshot (02 §One wire contract). Every later task
that adds a route regenerates both as part of its own definition of
done.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version as _distribution_version
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

from athanore.api.errors import install_error_handlers
from athanore.api.middleware import BodyLimitMiddleware
from athanore.engine import Engine
from athanore.settings import AthanoreSettings
from athanore.store.clock import now
from athanore.store.uow import Store

__all__ = ["VERSION", "Health", "create_app"]

#: The installed distribution version. `/api/health` reports it, and it
#: is the OpenAPI document's version too: the API is versioned by the
#: package version (08 §Versioning).
VERSION = _distribution_version("athanore")


# A model's docstring is its `description` in the published document, so
# these say what a client needs and nothing about the build. T043 adds
# the counts the full response carries — `runs_running`,
# `tasks_in_progress`, `pools` — once there is an engine to count them.
class Health(BaseModel):
    """Liveness and version. Unauthenticated, and carries no ids."""

    ok: bool = Field(description="True whenever the server answers at all.")
    version: str = Field(description="The running Athanore version.")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """The application's startup and shutdown, which do nothing yet.

    It exists now so that the hook is part of the published factory
    rather than something a later task retrofits. Nothing the API owns
    has a lifecycle: the engine, the store and the event bus are started
    and stopped by whoever built them and handed them here (04
    §Shutdown), because an application that started an engine it did not
    own would stop one out from under a host still using it.
    """

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

    The collaborators are put on `app.state` rather than closed over:
    dependencies reach them through `request.app.state`, which is what
    lets a router be a plain module-level `APIRouter` instead of a
    factory (08 §Endpoints).
    """

    settings = settings if settings is not None else AthanoreSettings()

    app = FastAPI(title="Athanore", version=VERSION, lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.store = store
    app.state.plugins = plugins
    # When this process came up. `/api/me` reports it (T043) and the
    # SPA refetches the plugin manifest whenever it changes (09).
    app.state.started_at = now()

    # Outermost of the application's own middleware: the body cap has to
    # run before anything reads a byte of the request (08 §Sizes).
    app.add_middleware(BodyLimitMiddleware, limit=settings.body_limit)
    install_error_handlers(app)

    @app.get("/api/health", tags=["system"], summary="Liveness and version")
    async def health() -> Health:
        return Health(ok=True, version=VERSION)

    return app

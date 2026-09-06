"""The FastAPI application factory.

`create_app` is the one way an Athanore server is built: the CLI, the
programmatic `Server` host and the tests all call it, and its signature
is the published one (02 §Package layout). The collaborators it takes
are accepted and unused today — they are the shape T042 onward fills in,
not a stub of behaviour.

What it exposes now is the single unauthenticated route of 08 §System,
`GET /api/health`. That is enough to freeze the wire contract: the
OpenAPI document generated from this app is committed as
`tests/snapshots/openapi.json`, and the SPA's TypeScript client is
generated from that snapshot (02 §One wire contract). Every later task
that adds a route regenerates both as part of its own definition of
done.
"""

from __future__ import annotations

from importlib.metadata import version as _distribution_version
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

from athanore.settings import AthanoreSettings

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


def create_app(
    settings: AthanoreSettings | None = None,
    engine: Any = None,
    store: Any = None,
    plugins: Any = None,
) -> FastAPI:
    """Build the ASGI application.

    `engine`, `store` and `plugins` are untyped here only because their
    classes do not exist yet; they become `Engine`, `Store` and the
    plugin registry in T042/T049.
    """
    app = FastAPI(title="Athanore", version=VERSION)

    @app.get("/api/health", tags=["system"], summary="Liveness and version")
    async def health() -> Health:
        return Health(ok=True, version=VERSION)

    return app

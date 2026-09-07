"""``GET /api/health`` and ``GET /api/me`` (08 §System).

The two routes that answer before anything is authenticated, and the only
two that never can be: `/api/health` is what a supervisor polls and what
``athanore serve`` waits for, and `/api/me` is how the SPA finds out
whether it needs a token at all. Requiring a credential to ask "do I need
a credential?" would be a loop with no way out, so both are open on every
bind — and neither returns an id, a title or anything else about the work
in flight (12 §Trust boundaries).

What they do report is real. `runs_running`, `tasks_in_progress` and
`pools` come from the store and the engine as they stand; when the
application was built without one of those collaborators the field is
**omitted**, never zero-filled, because "no store to ask" and "nothing
running" are different facts and a monitor that could not tell them apart
would report a drained server as healthy (02 §Real data only). A bare
:func:`~athanore.api.app.create_app` — the OpenAPI dump, a unit test — is
the only way that happens; a served application always has both.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from athanore.api import VERSION
from athanore.api.deps import AuthMode, auth_mode, authenticated

__all__ = ["Health", "Me", "PoolHealth", "router"]

router = APIRouter(prefix="/api", tags=["system"])


# A model's docstring is its `description` in the published document, so
# these say what a client needs and nothing about the build.
class PoolHealth(BaseModel):
    """One pool's capacity and what it is spending right now."""

    capacity: int = Field(description="Slots the pool has, in total.")
    in_flight: int = Field(description="Slots leased right now.")


class Health(BaseModel):
    """Liveness, version and counts. Unauthenticated, and carries no ids."""

    ok: bool = Field(description="True whenever the server answers at all.")
    version: str = Field(description="The running Athanore version.")
    runs_running: int | None = Field(
        default=None,
        description=(
            "Runs in the `running` status. Omitted when this application "
            "has no store to ask."
        ),
    )
    tasks_in_progress: int | None = Field(
        default=None,
        description=(
            "Attempts in the `in_progress` status; a task parked on a "
            "human is `waiting` and is not counted. Omitted when this "
            "application has no store to ask."
        ),
    )
    pools: dict[str, PoolHealth] | None = Field(
        default=None,
        description=(
            "Every registered pool by name. Omitted when this application "
            "has no engine; empty when the engine has no pools."
        ),
    )


class Me(BaseModel):
    """What the caller may do, and which server they are talking to."""

    auth: AuthMode = Field(
        description=(
            "`token` when operator endpoints require a bearer token, "
            "`off` on a plain loopback bind."
        )
    )
    authenticated: bool = Field(
        description=(
            "Whether this request carries operator rights. Always true "
            "when `auth` is `off`."
        )
    )
    version: str = Field(description="The running Athanore version.")
    started_at: datetime = Field(
        description=(
            "When this process came up. A change means a restart, which "
            "is the SPA's cue to refetch the plugin manifest."
        )
    )
    features: list[str] = Field(
        description="Optional capabilities this server has. Empty in v1."
    )


@router.get(
    "/health",
    summary="Liveness and version",
    response_model_exclude_none=True,
)
async def health(request: Request) -> Health:
    """Whether the server is up, which version it is, and what it is doing.

    Pausing every run and then waiting for `tasks_in_progress` to reach
    zero here is how an operator drains a server before stopping it.
    """

    # The counts are two reads on a pooled connection, taken without the
    # writer lock, so polling this route can never hold up a commit
    # (07 §Concurrency) — and 04 §Shutdown's drain recipe can be a loop.
    state = request.app.state
    engine = state.engine
    store = state.store

    pools: dict[str, PoolHealth] | None = None
    if engine is not None:
        pools = {
            name: PoolHealth(capacity=counts["capacity"], in_flight=counts["in_flight"])
            for name, counts in engine.snapshot().items()
        }

    runs_running: int | None = None
    tasks_in_progress: int | None = None
    if store is not None:
        async with store.reader() as reader:
            runs_running = await reader.runs.count_running()
            tasks_in_progress = await reader.tasks.count_in_progress()

    return Health(
        ok=True,
        version=VERSION,
        runs_running=runs_running,
        tasks_in_progress=tasks_in_progress,
        pools=pools,
    )


@router.get("/me", summary="Whether the caller needs a token, and has one")
async def me(request: Request) -> Me:
    """Whether this server wants a token, and whether this request has one.

    Never requires one itself: a request with no credential on a server
    that wants one gets a 200 saying `{"auth": "token", "authenticated":
    false}`, which is the client's cue to ask for a token.
    """

    settings = request.app.state.settings
    return Me(
        auth=auth_mode(settings),
        authenticated=authenticated(request),
        version=VERSION,
        started_at=request.app.state.started_at,
        features=[],
    )

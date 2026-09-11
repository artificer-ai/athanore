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

The lifespan starts what the application itself owns and nothing else:
the MCP endpoint's session manager, because the application mounted it
(08 §MCP), and the plugin event dispatcher, because the subscription it
holds is one this application took (09). Starting the engine belongs to
the host that owns it (T031), not to the application it serves.

The OpenAPI document generated from this app is committed as
`tests/snapshots/openapi.json`, and the SPA's TypeScript client is
generated from that snapshot (02 §One wire contract). Every task that
adds a route regenerates both as part of its own definition of done.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI

from athanore.api import VERSION
from athanore.api.deps import check_operator_token
from athanore.api.errors import install_error_handlers
from athanore.api.mcp import mount as mount_mcp
from athanore.api.middleware import BodyLimitMiddleware
from athanore.api.openapi import (
    AGENT_RESPONSES,
    OPERATOR_BEARER,
    OPERATOR_RESPONSES,
    TAGS,
    TASK_TOKEN,
    install_openapi,
    secure,
)
from athanore.api.registrar import WorkflowRegistrar
from athanore.api.routers import agent, requests, runs, system, tasks, workflows
from athanore.api.sse import router as sse_router
from athanore.api.static import install_cors, mount_spa
from athanore.engine import Engine
from athanore.plugins.context import PluginHost
from athanore.plugins.mount import MountedPlugins
from athanore.plugins.registry import PluginSpec
from athanore.settings import AthanoreSettings
from athanore.store.clock import now
from athanore.store.uow import Store

__all__ = ["VERSION", "create_app"]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """The application's startup and shutdown.

    Two collaborators have a lifecycle the application owns. The MCP
    server's session manager holds the task group each request's server
    instance runs in and therefore serves nothing until it is entered (08
    §MCP). The plugin event dispatcher is one subscription on the engine's
    bus, and it can only be taken once there is a loop to consume it in
    (09 §Wire contract) — so it is started here and closed here, and a
    handler that outlived the application would otherwise be delivering
    events into a store on its way down. It is started whether or not a
    spec with handlers is mounted yet: the subscription is the one every
    later ``add`` swaps its handlers under (22 §Live mounting, D236).

    Everything else — the engine, the store, the event bus — is started
    and stopped by whoever built it and handed it here (04 §Shutdown),
    because an application that started an engine it did not own would
    stop one out from under a host still using it.
    """

    plugins: MountedPlugins = app.state.plugins
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(app.state.mcp.run())
        if plugins.dispatch is not None:
            plugins.dispatch.start()
            stack.push_async_callback(plugins.dispatch.aclose)
        yield


def create_app(
    settings: AthanoreSettings | None = None,
    engine: Engine | None = None,
    store: Store | None = None,
    plugins: Sequence[PluginSpec] | None = None,
    registrar: WorkflowRegistrar | None = None,
) -> FastAPI:
    """Build the ASGI application.

    `settings` defaults to a freshly loaded :class:`AthanoreSettings`, so
    a bare `create_app()` is the server the environment describes.
    `plugins` are the collected, **validated** specs of the registered
    workflows (09): the host that registered them is what checked them,
    and this application mounts what it is given. They become the first
    entries of the :class:`~athanore.plugins.mount.MountedPlugins` on
    ``app.state.plugins``, which is where a host adds, replaces and
    removes a workflow's surface while the application serves (22 §Live
    mounting). `registrar` is the host's end of the three registration
    routes (:class:`~athanore.api.registrar.WorkflowRegistrar`, 22
    §Wire): every application a :class:`~athanore.server.Server` builds
    has one, and one built without — the OpenAPI dump, a test that wants
    none — answers ``POST``, ``PUT`` and ``DELETE /api/workflows`` with
    ``503 registration_unavailable``.

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

    app = FastAPI(
        title="Athanore",
        version=VERSION,
        lifespan=lifespan,
        openapi_tags=TAGS,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.store = store
    app.state.registrar = registrar
    # When this process came up. `/api/me` reports it and the SPA
    # refetches the plugin manifest whenever it changes (09).
    app.state.started_at = now()

    # The body cap has to run before anything reads a byte of the
    # request (08 §Sizes), so it is added first and everything the
    # request passes through afterwards is inside it.
    app.add_middleware(BodyLimitMiddleware, limit=settings.body_limit)
    # ...except CORS, which is added after and therefore wraps it: a
    # preflight is answered without reaching the cap, and a 413 still
    # carries the headers the browser needs to read it. Nothing at all
    # when `cors_origins` is unset, which is the default (12).
    install_cors(app, settings)
    install_error_handlers(app)
    # Who may call what, in the document as well as in the code (08
    # §OpenAPI): every router that depends on `operator_auth` declares
    # `operatorBearer` and the 401 it answers without it, the agent
    # router declares `taskToken` and its 403, and the system router
    # declares neither because it is unauthenticated on any bind. Both
    # sets carry the 422 of 08 §Conventions, which is what keeps FastAPI
    # from writing one of its own.
    for operator in (workflows.router, runs.router, tasks.router, requests.router):
        secure(operator, OPERATOR_BEARER)
    secure(sse_router, OPERATOR_BEARER)
    secure(agent.router, TASK_TOKEN)
    app.include_router(system.router)
    app.include_router(workflows.router, responses=OPERATOR_RESPONSES)
    app.include_router(runs.router, responses=OPERATOR_RESPONSES)
    app.include_router(tasks.router, responses=OPERATOR_RESPONSES)
    app.include_router(requests.router, responses=OPERATOR_RESPONSES)
    app.include_router(agent.router, responses=AGENT_RESPONSES)
    # Not under `routers/`: the stream is one endpoint and a generator,
    # and 02 §Package layout gives it its own module (`api/sse.py`).
    app.include_router(sse_router, responses=OPERATOR_RESPONSES)
    # Last, and not a router: the same five capabilities as MCP tools,
    # on a mounted ASGI application with its own auth at the door (08
    # §MCP). The manager it returns is what `lifespan` runs.
    app.state.mcp = mount_mcp(app, settings)
    # The last wrapper on the document's generation, so what it declares
    # — the security schemes, and the 422 it prunes — covers the MCP path
    # item the line above inserts as well as the generated routes (08
    # §OpenAPI).
    install_openapi(app)
    # The plugin surface: the manifest and the actions endpoint once,
    # then one router per workflow at `/api/plugins/{workflow}` under the
    # same operator door as everything else (09 §Mounting, 12 §Plugins),
    # and the JavaScript a workflow ships beside them at
    # `/plugins/{workflow}/static/` (09 §Escape hatch) — not under
    # `/api/`, because it is a document's asset rather than an
    # operation, served by `StaticFiles` under the SPA's own
    # content-security policy. The collection is live: what a host adds
    # or removes later is mounted the same way (22 §Live mounting). The
    # dispatcher it owns is built here and started by `lifespan`, and
    # only where there is an engine: no engine, no bus, no events.
    app.state.plugins = MountedPlugins(
        app,
        settings,
        bus=engine.bus if engine is not None else None,
        host=PluginHost.from_app(app) if engine is not None else None,
    )
    for spec in plugins if plugins is not None else ():
        app.state.plugins.add(spec)
    # The SPA at `/`, as the router's fallback rather than as a route:
    # every route is matched first — including the ones a plugin
    # registers after this call — and an unmatched path is the client
    # router's (08 §Static).
    mount_spa(app, settings=settings)

    return app

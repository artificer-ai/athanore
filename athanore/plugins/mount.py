"""Turning declarations into live routes, a manifest, and subscriptions.

09 §Mounting and §Wire contract. Three things happen here and nothing
else does:

- :func:`mount` builds one ``APIRouter`` per workflow at
  ``/api/plugins/{workflow}``, under ``Depends(operator_auth)``. **A
  plugin does not get an auth model of its own** (12 §Plugins): its
  routes are operator routes, they answer 401 on a bind that requires a
  token like every other operator route, and they say so in the
  document.
- :func:`mount_manifest` adds ``GET /api/plugins``, the static list the
  SPA fetches at boot and again whenever ``/api/me`` reports a new
  ``started_at``. Builtins come first, under the ``_builtin`` workflow,
  because the operator's own views are the ones the pane host lays out
  before anything a workflow contributed (09 §Builtins are plugins).
- :func:`dispatch_handlers` subscribes **once** to the bus and calls the
  ``on`` handlers that match each event. The bus is fed by the store's
  outbox after the commit, so a handler sees only state that is durable,
  and it runs in the dispatcher's own task rather than in the
  transaction — which is what makes the next paragraph true.

**A plugin cannot break the engine.** A handler that raises is logged
and dropped: the transaction that emitted the event has already
committed, the other handlers still run, and the run carries on. A
handler that is merely slow costs its subscription events rather than
stalling a writer, because the bus never awaits a subscriber (D29).

This module reaches up into :mod:`athanore.api` for two things and two
only — the operator dependency, and the OpenAPI security requirement
that documents it. Both are named exemptions in the layering contract
(D138): a plugin route *is* an API route, so the door it hangs on is the
API's, and there is no lower place to put a door that has to be the same
one.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import AsyncIterator, Callable, Iterable, Sequence
from contextlib import suppress
from typing import Annotated, Any, get_type_hints

from fastapi import APIRouter, Depends, FastAPI, Query, Request
from pydantic import BaseModel, Field

from athanore.api.deps import operator_auth
from athanore.api.openapi import OPERATOR_BEARER, OPERATOR_RESPONSES, secure
from athanore.events import names
from athanore.events.bus import EventBus, Subscription
from athanore.events.model import Event
from athanore.logging import get_logger
from athanore.plugins.context import PluginContext, PluginHost, owns_run
from athanore.plugins.decl import Handler, PanelKind, Placement, Route, Slot
from athanore.plugins.registry import BUILTIN_WORKFLOW, PluginSpec, manifest_entry

__all__ = [
    "MANIFEST_PATH",
    "ActionOut",
    "HandlerDispatch",
    "PanelOut",
    "PluginManifestEntry",
    "dispatch_handlers",
    "mount",
    "mount_manifest",
    "mount_plugins",
]

_log = get_logger(__name__)

#: Where the manifest lives (08 §Plugins).
MANIFEST_PATH = "/api/plugins"


class PanelOut(BaseModel):
    """One panel of the manifest (09 §Wire contract).

    ``source`` is the mounted URL of the route the panel's data comes
    from, or — for a ``form`` panel — the name of the action whose model
    is the form. ``node`` is present only on a panel that follows one;
    whether that node is *live* travels on the run's graph rather than
    here, because the manifest changes only on restart (08 §Graph
    semantics).
    """

    name: str = Field(description="The panel's title, unique within its workflow.")
    slot: Slot = Field(description="Where the panel is shown (09 §Slots).")
    placement: Placement = Field(
        description="A pane of its own, or a card on the run overview."
    )
    kind: PanelKind = Field(description="Which renderer draws it, and its data shape.")
    scope: Slot = Field(description="What has to be resolved before it can load.")
    node: str | None = Field(
        default=None, description="The node this panel follows, when it follows one."
    )
    source: str | None = Field(
        default=None,
        description="The URL its data comes from, or the action name for a form.",
    )
    element: str | None = Field(
        default=None, description="The custom element tag a `custom` panel renders."
    )
    refresh_on: list[str] = Field(
        default_factory=list,
        description="Event-name globs that invalidate this panel's data.",
    )


class ActionOut(BaseModel):
    """One action of the manifest, and the form the SPA renders for it."""

    name: str = Field(description="The action's name, as its URL spells it.")
    title: str = Field(description="What the button and the palette entry say.")
    scope: Slot = Field(description="What has to be resolved before it can run.")
    confirm: bool = Field(
        description="Whether the SPA asks for confirmation before calling it."
    )
    schema_: dict[str, Any] = Field(
        alias="schema",
        description="JSON Schema of the input model — the form itself.",
    )


class PluginManifestEntry(BaseModel):
    """What one workflow contributes to the UI (09 §Wire contract)."""

    workflow: str = Field(
        description="The workflow that declared these, or `_builtin` for the "
        "views the core ships."
    )
    panels: list[PanelOut] = Field(
        default_factory=list, description="Its panels, in declaration order."
    )
    actions: list[ActionOut] = Field(
        default_factory=list, description="Its actions, in declaration order."
    )
    assets: list[str] = Field(
        default_factory=list,
        description="URLs of the JavaScript modules the SPA injects for it.",
    )


def mount_plugins(app: FastAPI, specs: Sequence[PluginSpec]) -> None:
    """Mount every spec on ``app``, and the manifest that lists them.

    What :func:`athanore.api.app.create_app` calls. The manifest route
    exists whether or not anything is registered: a server with no
    plugins answers with an empty list, which is a fact the SPA can act
    on, rather than a 404 it has to special-case.
    """

    mount_manifest(app)
    for spec in specs:
        mount(app, spec)


def mount(app: FastAPI, spec: PluginSpec) -> APIRouter:
    """Mount one workflow's routes at ``/api/plugins/{workflow}``.

    Returns the router, mounted. Every route depends on
    ``operator_auth``, declares the operator security scheme and the 401
    that goes with it, and takes ``run_id`` / ``task_id`` / ``node``
    query parameters wherever its handler asked for a
    :class:`~athanore.plugins.context.PluginContext`.

    Actions are **not** mounted here: they are one endpoint,
    ``POST /api/plugins/{wf}/actions/{name}``, and it is T070's.
    """

    router = APIRouter(
        prefix=spec.prefix,
        tags=["plugins"],
        dependencies=[Depends(operator_auth)],
    )
    for route in spec.routes:
        router.add_api_route(
            route.path,
            _endpoint(spec, route),
            methods=list(route.methods),
            name=f"plugin:{spec.workflow}:{route.fn.__name__}",
            summary=_summary(route),
        )
    secure(router, OPERATOR_BEARER)
    app.include_router(router, responses=OPERATOR_RESPONSES)
    return router


def mount_manifest(app: FastAPI) -> APIRouter:
    """Add ``GET /api/plugins`` to ``app``, reading ``app.state.plugins``.

    Read per request rather than closed over, like every other
    collaborator in the API (08 §Endpoints) — and because the asset list
    is read off disk when it is asked for, so a build that lands under a
    running server needs no restart to be listed.
    """

    router = APIRouter(prefix=MANIFEST_PATH, tags=["plugins"])

    @router.get(
        "",
        summary="Everything the registered workflows contribute to the UI",
        response_model_exclude_none=True,
        dependencies=[Depends(operator_auth)],
    )
    async def manifest(request: Request) -> list[PluginManifestEntry]:
        """The plugin manifest: panels, actions and assets, per workflow.

        Builtins first, then the workflows in registration order. The
        SPA fetches this at boot and again whenever the SSE stream
        reconnects onto a server with a new ``started_at``, because a
        manifest changes only when the process does (09 §Wire contract).
        """

        specs: Sequence[PluginSpec] = getattr(request.app.state, "plugins", None) or ()
        return [
            PluginManifestEntry.model_validate(manifest_entry(spec))
            for spec in _builtins_first(specs)
        ]

    secure(router, OPERATOR_BEARER)
    app.include_router(router, responses=OPERATOR_RESPONSES)
    return router


def _builtins_first(specs: Iterable[PluginSpec]) -> list[PluginSpec]:
    """``specs`` with the builtin entry in front, order otherwise kept.

    A stable partition rather than a sort: the order workflows were
    registered in is the order the library lists them, and the one thing
    09 fixes is that the core's own views come first.
    """

    ordered = list(specs)
    return [spec for spec in ordered if spec.workflow == BUILTIN_WORKFLOW] + [
        spec for spec in ordered if spec.workflow != BUILTIN_WORKFLOW
    ]


def _in_scope(workflow: str, owner: str | None, event: Event) -> bool:
    """May a plugin of ``workflow`` be handed ``event``?

    Ownership, and nothing else (09 §Declarations: an ``on`` handler
    inherits the workflow it was declared on, and scope follows
    ownership).

    An event with no run at all — the ``engine.*`` names — is about the
    server rather than about anyone's work, and reaches every
    subscriber. An event about a run whose owner cannot be established —
    the row is gone and the payload does not name the workflow — reaches
    only the builtin scope, which owns every run there is. Delivering it
    to everybody instead would hand one workflow another's run ids and
    titles, which is the reach 12 §Plugins forbids.
    """

    if event.run_id is None:
        return True
    if owner is None:
        return workflow == BUILTIN_WORKFLOW
    return owns_run(workflow, owner)


def _summary(route: Route) -> str:
    """The one-line summary a plugin route shows in the document."""

    doc = inspect.getdoc(route.fn)
    return doc.splitlines()[0] if doc else route.fn.__name__


def _endpoint(spec: PluginSpec, route: Route) -> Callable[..., Any]:
    """``route.fn`` as something FastAPI can mount.

    One rewrite and one wrapper. The rewrite replaces the annotation of
    the ``ctx: PluginContext`` parameter with a dependency, which is what
    makes ``run_id`` / ``task_id`` / ``node`` query parameters of the
    route and the resolved context the handler's first argument; every
    other parameter is left exactly as the author annotated it, so 09's
    "any other parameter follows normal FastAPI rules" is not a claim
    this module has to implement.

    The wrapper is what awaits the result. 09's handlers are ``async
    def``; a synchronous one is called inline rather than refused,
    because a plugin route that reads a dict and returns it has nothing
    to await and no reason to be rejected for it.
    """

    fn = route.fn
    signature = inspect.signature(fn)
    hints = _hints(fn)
    dependency = _context_dependency(spec.workflow)
    parameters = [
        parameter.replace(
            annotation=(
                Annotated[PluginContext, Depends(dependency)]
                if hints.get(parameter.name, parameter.annotation) is PluginContext
                else hints.get(parameter.name, parameter.annotation)
            )
        )
        for parameter in signature.parameters.values()
    ]

    async def endpoint(**kwargs: Any) -> Any:
        result = fn(**kwargs)
        return await result if inspect.isawaitable(result) else result

    endpoint.__name__ = fn.__name__
    endpoint.__doc__ = fn.__doc__
    # What `inspect.signature` reads, and therefore what FastAPI builds
    # the route's parameters from.
    endpoint.__signature__ = signature.replace(  # pyright: ignore[reportFunctionMemberAccess]
        parameters=parameters,
        return_annotation=hints.get("return", signature.return_annotation),
    )
    return endpoint


def _hints(fn: Callable[..., Any]) -> dict[str, Any]:
    """``fn``'s annotations, resolved, or its raw ones if they cannot be.

    Every module in this package carries ``from __future__ import
    annotations``, so an author's are strings and have to be resolved
    before ``PluginContext`` can be recognised. A module whose hints name
    something this process cannot import falls back to the raw
    annotations rather than failing registration: FastAPI will report
    what it cannot build, and it says it better than a ``NameError``
    from here would.
    """

    try:
        return get_type_hints(fn, include_extras=True)
    except Exception:
        _log.warning("plugin handler annotations could not be resolved", fn=fn.__name__)
        return {}


def _context_dependency(
    workflow: str,
) -> Callable[..., AsyncIterator[PluginContext]]:
    """The FastAPI dependency that resolves a :class:`PluginContext`.

    One per workflow, because the workflow is what the ownership check
    is made against: a ``run_id`` of another workflow's run is a 404
    before the handler runs (09 §Context and scopes).

    A generator dependency, so that whatever the context opened is
    closed when the response is done — the transcript service starts a
    background flusher on its first append, and a request-scoped one
    that nobody closed would outlive the request.
    """

    async def resolve(
        request: Request,
        run_id: Annotated[
            str | None, Query(description="The run to resolve the context against.")
        ] = None,
        task_id: Annotated[
            int | None, Query(description="The task attempt to resolve.")
        ] = None,
        node: Annotated[
            str | None, Query(description="The node the panel or action is for.")
        ] = None,
    ) -> AsyncIterator[PluginContext]:
        host = PluginHost.from_app(request.app)
        context = await host.context(
            workflow=workflow, run_id=run_id, task_id=task_id, node=node
        )
        try:
            yield context
        finally:
            await context.aclose()

    return resolve


class HandlerDispatch:
    """One subscription, and the ``on`` handlers it feeds.

    Constructed by :func:`dispatch_handlers`, which also starts it.
    ``aclose()`` closes the subscription and waits for the consumer task,
    so a host that stops the application does not leave one draining the
    bus into handlers whose store is being torn down.
    """

    def __init__(
        self,
        bus: EventBus,
        specs: Sequence[PluginSpec],
        host: PluginHost | None = None,
    ) -> None:
        self._bus = bus
        #: Only the specs that subscribe to anything: a workflow with no
        #: ``on`` handler costs nothing per event.
        self.specs = tuple(spec for spec in specs if spec.handlers)
        self._host = host if host is not None else PluginHost(None)
        self._subscription: Subscription | None = None
        self._task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        """Whether the consumer task is live."""

        return self._task is not None and not self._task.done()

    def start(self) -> None:
        """Subscribe and begin delivering. Idempotent, and a no-op if
        nothing subscribes."""

        if self._task is not None or not self.specs:
            return
        # Before the first delivery, and to everything: the filtering is
        # per handler, and one subscription is what 09 asks for.
        self._subscription = self._bus.subscribe()
        self._task = asyncio.create_task(self._consume(), name="plugin-handlers")

    async def aclose(self) -> None:
        """Stop delivering and let go of the bus. Idempotent."""

        if self._subscription is not None:
            self._subscription.close()
            self._subscription = None
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def _consume(self) -> None:
        """Deliver every event this subscription sees, until cancelled."""

        subscription = self._subscription
        if subscription is None:  # pragma: no cover - `start` sets it first
            return
        while True:
            event = await subscription.queue.get()
            if subscription.overflowed:
                # Say it once per gap; the flag stays set, so it is reset
                # here to make the next drop its own line rather than a
                # log entry per event for the rest of the process.
                subscription.overflowed = False
                _log.warning("plugin handlers fell behind and lost events")
            try:
                await self._deliver(event)
            except asyncio.CancelledError:
                raise
            except Exception:
                # The same log-and-continue this module promises a
                # handler, applied one level out. The awaits around the
                # handlers — the owner lookup's store read, and the
                # transcript flush a context closes with — are store
                # calls, and a store that failed once must not take the
                # only consumer of the bus with it: the subscription
                # would stay open, the queue would fill, and every
                # `on` handler in the process would stop firing with
                # nothing said until shutdown.
                _log.error(
                    "plugin event delivery failed",
                    event_name=event.name,
                    run_id=event.run_id,
                    exc_info=True,
                )

    async def _deliver(self, event: Event) -> None:
        """Call every handler this event matches, in registration order.

        A run belongs to one workflow, so a spec is skipped outright
        unless the run is its own — the ownership rule of 09, applied
        before a handler is ever entered.

        The matching is done first and the owner looked up only if
        something matched, because the lookup is a store read and most
        events on the bus subscribe nobody.
        """

        matched: list[tuple[PluginSpec, list[Handler]]] = []
        for spec in self.specs:
            handlers = [
                handler
                for handler in spec.handlers
                if names.matches(handler.event, event.name)
            ]
            if handlers:
                matched.append((spec, handlers))
        if not matched:
            return
        owner = await self._owner(event)
        for spec, handlers in matched:
            if not _in_scope(spec.workflow, owner, event):
                continue
            await self._call(spec, handlers, event)

    async def _owner(self, event: Event) -> str | None:
        """The workflow whose run ``event`` is about, or ``None``.

        The store first, then the event's own payload. ``run.deleted`` is
        published by the transaction that deleted the run, so its row is
        deterministically gone by the time this asks — and 18 §Payloads
        puts the owning workflow on that payload, which is what keeps the
        last event of a run inside the workflow that owned it.
        """

        if event.run_id is None:
            return None
        owner = await self._host.workflow_of(event.run_id)
        if owner is not None:
            return owner
        workflow = event.data.get("workflow")
        return workflow if isinstance(workflow, str) else None

    async def _call(
        self, spec: PluginSpec, handlers: Sequence[Handler], event: Event
    ) -> None:
        """Build one context for ``spec`` and run its handlers under it.

        Resolved with ``strict=False``: the run of a ``run.deleted`` is
        already gone, and a handler that subscribed to that event asked
        precisely because it is, so it is handed a context with no run in
        scope rather than nothing at all.
        """

        try:
            context = await self._host.context(
                workflow=spec.workflow,
                run_id=event.run_id,
                task_id=event.task_id,
                strict=False,
            )
        except Exception:
            _log.error(
                "plugin context could not be resolved",
                workflow=spec.workflow,
                event_name=event.name,
                exc_info=True,
            )
            return
        try:
            for handler in handlers:
                await self._one(spec, handler, context, event)
        finally:
            try:
                await context.aclose()
            except asyncio.CancelledError:
                raise
            except Exception:
                # A transcript's final flush is a store write, and one
                # spec's cleanup failing is not a reason to skip the
                # specs after it.
                _log.error(
                    "plugin context could not be closed",
                    workflow=spec.workflow,
                    event_name=event.name,
                    exc_info=True,
                )

    async def _one(
        self, spec: PluginSpec, handler: Handler, context: PluginContext, event: Event
    ) -> None:
        """Call one handler, and swallow whatever it raises.

        Logged with its traceback and dropped. The engine is not
        involved: the transaction that emitted this event committed
        before the bus published it, this runs in the dispatcher's own
        task, and the handlers after it still run (09 §Wire contract).
        """

        try:
            result = handler.fn(context, event)
            if inspect.isawaitable(result):
                await result
        except asyncio.CancelledError:
            raise
        except Exception:
            _log.error(
                "plugin handler failed",
                workflow=spec.workflow,
                event_name=event.name,
                handler=getattr(handler.fn, "__name__", repr(handler.fn)),
                exc_info=True,
            )


def dispatch_handlers(
    bus: EventBus,
    specs: Sequence[PluginSpec],
    host: PluginHost | None = None,
) -> HandlerDispatch:
    """Subscribe once, and deliver committed events to the ``on`` handlers.

    Returns the started :class:`HandlerDispatch`; the caller closes it
    (``await dispatch.aclose()``), which is what the application's
    lifespan does. Requires a running event loop, because delivery is a
    task: everything this function subscribes to arrives after a commit,
    and there is nothing to deliver before the loop that does the
    committing exists.
    """

    dispatch = HandlerDispatch(bus, specs, host)
    dispatch.start()
    return dispatch

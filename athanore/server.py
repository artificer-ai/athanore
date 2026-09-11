"""The programmatic host: settings, store, engine, API and uvicorn (04
§Programmatic host).

.. code-block:: python

    server = Server()                       # settings from env / athanore.toml
    server.register(feature_build, Pool("local", 1))
    server.register_configured()            # the [workflows.<name>].target rows
    server.serve()                          # blocking
    # ...or `await server.start()` / `await server.stop()` in a test
    # ...and, on a serving server (22 §Server surface):
    await server.add(wf, target="workflows/chat.py:wf", persist=True)
    await server.replace(wf)
    await server.remove("chat")

This is the composition root and nothing else. Every object it wires
together already exists and already knows how to do its job; what lives
here is the *order* they are built in — at boot, and again for each of
the three live verbs, which sequence what the engine, the plugin host
and the store each provide exactly as 22 §Effects lists (engine step,
mount step, recovery, event, notify) — and the two refusals that keep a
misconfigured install from running at all:

- **A non-loopback bind with no operator token refuses to start.**
  :func:`athanore.api.deps.check_operator_token` is the check, and
  :func:`athanore.api.app.create_app` makes it a property of the
  application rather than of one host (D129). It is called again here,
  before anything touches the database, so the process fails without
  having migrated a file first (12 §Operator token).
- **A v0 database is refused, never migrated in place.** The MVP kept no
  ``alembic_version``, so ``alembic upgrade head`` against one would
  create v1's tables beside the MVP's and stamp a revision on a file that
  was never a v1 database — with the run history stranded in tables
  nothing reads. 07 §Importing a v0 database gives the one-way door
  (``athanore db import-v0``), and this refusal is what points at it.

The one ordering decision that is not obvious is the shutdown's. 04
§Shutdown stops the engine first and closes the HTTP surface last: the
attempts are cancelled and ``engine.stopping`` is recorded while the API
is still answering, and only then do the SSE streams close. Reversed, an
attempt would be cancelled with no way to report anything, and the
transcript flusher's last batch would meet a closed door.

``Server`` is the library surface; ``athanore serve`` (11) is the CLI
wrapper that discovers workflows, reads pools from ``athanore.toml`` and
drives this class.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
import socket
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI
from sqlalchemy.engine import make_url
from sse_starlette.sse import AppStatus

from athanore.api.app import create_app
from athanore.api.deps import MissingOperatorToken, check_operator_token
from athanore.cli.verbs import RESERVED
from athanore.engine import SHUTDOWN_BUDGET, Engine, Pool, recover
from athanore.events.bus import EventBus
from athanore.events.model import Event
from athanore.events.names import EventName
from athanore.events.payloads import (
    EventModel,
    WorkflowRegistered,
    WorkflowReplaced,
    WorkflowUnregistered,
)
from athanore.graph import Graph, GraphError
from athanore.logging import configure_logging, get_logger
from athanore.plugins.builtin import with_builtins
from athanore.plugins.decl import PluginError
from athanore.plugins.discovery import (
    Layout,
    LayoutError,
    LoadError,
    LoadStage,
    Registered,
    RemovedWorkflow,
    load_target,
    read_layout,
)
from athanore.plugins.mount import MountedPlugins
from athanore.plugins.persist import remove_row, write_row
from athanore.plugins.registry import (
    PluginSpec,
    PluginValidationError,
    collect,
    validate,
)
from athanore.requests.service import RequestService
from athanore.settings import AthanoreSettings
from athanore.store.clock import now
from athanore.store.engine import make_engine
from athanore.store.migrate import is_v0_database, upgrade
from athanore.store.retention import retention_loop
from athanore.store.uow import Store
from athanore.workflow import Workflow

# `MissingOperatorToken` is `athanore.api.deps`'s, re-exported here because
# the two refusals are one pair to whoever has to report them: they are
# the two ways `athanore serve` cannot serve, and it prints each as a
# sentence rather than a traceback (11 §Server). The CLI may not import
# the one from `api` itself — `api` and `cli` are independent siblings of
# the same tier (02 §Layering) — and the composition root, where both are
# already raised, is the one place that names both.
__all__ = [
    "AthanoreServer",
    "ConfiguredRows",
    "MissingOperatorToken",
    "Server",
    "Skipped",
    "V0Database",
]

_log = get_logger(__name__)

#: How long :meth:`Server.stop` waits for uvicorn to finish its graceful
#: shutdown, and what uvicorn is configured to give itself. 04 §Shutdown
#: step 5: "total budget 10 s; past it the process exits anyway
#: (uvicorn's ``timeout_graceful_shutdown``)" — the same number the
#: engine's own stop is bounded by, spelled once in
#: :data:`athanore.engine.SHUTDOWN_BUDGET`.
SHUTDOWN_TIMEOUT = SHUTDOWN_BUDGET

#: How often :meth:`Server.start` looks at a uvicorn that has not
#: finished binding yet. Short enough that a test that starts a server
#: does not feel it, long enough not to spin.
_BIND_POLL = 0.01

#: The addresses that mean "every interface". A browser cannot be pointed
#: at one, so :attr:`Server.url` reports loopback instead — the MVP's
#: behaviour, and the reason 12 §S6 gave ``public_url`` to agents.
_WILDCARD = frozenset({"0.0.0.0", "::", "[::]", ""})


#: The file every ``[workflows.<name>]`` row lives in, under the root path
#: the settings resolved (02 §``athanore.toml`` layout, 22 §Persistence).
TOML_NAME = "athanore.toml"


@dataclass(frozen=True)
class Skipped:
    """A ``[workflows.<name>].target`` row a prior registration shadowed.

    22 §Persistence: a positional that loads the same name wins and the
    row is skipped with a warning naming both targets. ``registered`` is
    the target of the registration that won, or ``None`` for a
    programmatic one.
    """

    name: str
    target: str
    registered: str | None


@dataclass(frozen=True)
class ConfiguredRows:
    """What :meth:`Server.register_configured` did, in the file's order."""

    registered: tuple[str, ...]
    skipped: tuple[Skipped, ...]


class V0Database(RuntimeError):
    """The configured database is an MVP database awaiting an import.

    Raised by :meth:`Server.start` before any migration runs, because
    migrating a v0 file in place is not recoverable: the MVP's tables
    would sit beside v1's under a stamped revision, and the history they
    hold would be readable by nothing (07 §Importing a v0 database).
    """


class _QuietUvicorn(uvicorn.Server):
    """A uvicorn that never installs signal handlers.

    :class:`Server` owns the process's lifecycle — :meth:`Server.serve`
    is what maps SIGINT and SIGTERM onto :meth:`Server.stop`, so that the
    engine's shutdown happens before the socket closes — and uvicorn's
    own handlers would take that decision first and only stop the HTTP
    half. It also makes a server startable from a thread or a test, where
    installing a signal handler raises.
    """

    def install_signal_handlers(self) -> None:
        return None


class Server:
    """One process serving the workflows registered on it.

    The collaborators are built here, in :meth:`__init__`, because
    :meth:`register` has to reach the engine before anything is started
    and because a SQLAlchemy engine connects lazily — constructing one
    touches no file, so a ``Server`` that is never started opens no
    database.

    :meth:`start` and :meth:`stop` may be called in either order any
    number of times: a stopped server starts again on the same store,
    with a fresh application and a fresh socket — on the port it was
    given the first time, since an ephemeral bind is adopted — which is
    what makes a whole test suite able to use one.
    """

    def __init__(self, settings: AthanoreSettings | None = None) -> None:
        self.settings = settings if settings is not None else AthanoreSettings()
        #: The bus every committed transaction publishes to, and the one
        #: the SSE feed and the plugin handlers subscribe to.
        self.bus = EventBus()
        self._sa_engine = make_engine(self._db_url)
        self.store = Store(self._sa_engine, self.bus)
        #: The human-in-the-loop channel. One per process (06 §Service):
        #: its registered validators belong to the waiters alive in *this*
        #: process, so the engine is handed this one rather than making
        #: its own.
        self.requests = RequestService(self.store, self.bus)
        self.engine = Engine(
            self.settings, self.store, self.bus, requests=self.requests
        )
        self.app: FastAPI | None = None
        self._workflows: dict[str, Workflow] = {}
        #: The target each registration was loaded from, or ``None`` for
        #: a programmatic one (22 §Terms); kept in step with `_workflows`.
        self._targets: dict[str, str | None] = {}
        self._specs: list[PluginSpec] = []
        self._config: uvicorn.Config | None = None
        self._uvicorn: _QuietUvicorn | None = None
        self._serve_task: asyncio.Task[None] | None = None
        self._retention_task: asyncio.Task[None] | None = None
        self._stopping: asyncio.Event | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._bound_port: int | None = None

    # -- registration ------------------------------------------------------

    def register(
        self, wf: Workflow, pool: Pool | None = None, *, target: str | None = None
    ) -> Server:
        """Finalize ``wf``, check its name, and run it on ``pool``.

        The boot-time idiom (22 §Server surface): sync, strict about
        duplicates, chains. Three names must not collide, and all three
        are checked here rather than at the moment the collision would
        be felt:

        1. a **CLI verb** (:data:`athanore.cli.verbs.RESERVED`), because
           ``athanore <workflow> "title"`` is the MVP's shorthand for
           ``submit`` and a workflow called ``ls`` could never be
           submitted that way (11 §Verbs);
        2. a **pool**, because ``athanore.toml``'s ``[pools]`` and
           ``[workflows]`` tables would not know which of the two they
           were naming (04 §Pools) — refused by the pool registry, which
           owns that namespace;
        3. a **workflow already registered**, because rebinding the name
           would leave the attempts in flight running the graph this call
           replaced.

        The plugin declarations are collected and validated here too, so
        a workflow whose panel names a node it does not have is refused
        at registration rather than mounted broken (09).

        ``target`` is the string the workflow was loaded from, recorded
        for :attr:`targets`; ``None`` for a workflow the host built.
        After :meth:`start` this raises ``RuntimeError`` — the call
        would enter the graph and mount nothing (D226); :meth:`add` is
        the live verb.

        Returns the server, so registrations chain.
        """

        self._before_start("register")
        graph = self._finalize(wf)
        name = graph.name
        self._check_name(name)
        spec = self._check_plugins(wf, graph)
        # Last, because it is the only step that mutates anything: a
        # refusal above leaves the server exactly as it was.
        self.engine.register(graph, pool)
        self._record(name, wf, target, spec)
        return self

    def register_configured(self) -> ConfiguredRows:
        """Register the ``[workflows.<name>].target`` rows (22 §Persistence).

        Reads the file the settings resolved (``root_path /
        athanore.toml``) and, for each row with a ``target`` in the
        file's order, loads it through :func:`load_target` and calls
        :meth:`register` with its target and, when the row names one,
        the pool ``[pools]`` declares for it. The rules a row is held to:

        - its key MUST be the loaded workflow's name — the row is the
          registration, and one under the wrong name is a typo that
          would register something the operator did not write down;
          ``LoadError`` (stage ``register``) otherwise;
        - a name already registered wins — ``athanore serve``'s
          positional, or a ``register`` the host made first — and the
          row is skipped, reported in ``skipped`` and logged at WARNING
          naming both targets;
        - a pool ``[pools]`` does not declare is a ``LayoutError``, the
          price ``athanore serve`` puts on any binding it cannot honour.

        A file with no such rows registers nothing; a missing file is
        not an error. Rows without a target are bindings only and are
        not read here. Before :meth:`start` only, as :meth:`register`.
        """

        self._before_start("register_configured")
        path = self.toml_path
        layout = read_layout(path)
        registered: list[str] = []
        skipped: list[Skipped] = []
        for key, target in layout.targets.items():
            wf = load_target(target)
            if wf.name != key:
                detail = (
                    f"`[workflows.{key}]` in {path} names {target}, which is the "
                    f"workflow {wf.name!r}; a row's key must be the workflow's "
                    f"name."
                )
                raise LoadError(detail, stage="register", target=target, detail=detail)
            if key in self._workflows:
                shadowed = Skipped(key, target, self._targets[key])
                skipped.append(shadowed)
                _log.warning(
                    "a registered workflow shadows an athanore.toml row",
                    workflow=key,
                    row_target=target,
                    registered_target=shadowed.registered,
                    path=str(path),
                )
                continue
            self.register(wf, _pool_of(layout, key, path), target=target)
            registered.append(key)
        return ConfiguredRows(tuple(registered), tuple(skipped))

    async def add(
        self,
        wf: Workflow,
        pool: str | Pool | None = None,
        *,
        target: str | None = None,
        persist: bool = False,
    ) -> Registered:
        """Register ``wf`` on a server that may already be serving (22 §Add).

        Every refusal :meth:`register` makes, this makes first — a verb
        or pool name, a duplicate, a graph that does not finalize, a
        declaration that does not validate — each as a :class:`LoadError`
        naming its stage, and a duplicate with ``conflict`` set. Then,
        with ``persist``, the row is written (see :meth:`_persist_row`).
        Only then is anything mutated, in 22 §Effects' order: the engine
        registers the graph on ``pool`` — a name, or a :class:`Pool`
        whose name is read (:meth:`_resolve_pool`); serving, the plugin
        spec is mounted into the live application, the name's orphaned
        rows are recovered (``engine.recovered``, when there were any),
        ``workflow.registered`` is emitted, and the scheduler is notified.
        Before :meth:`start` only the registries change and nothing is
        emitted — there is no application to mount into and no store to
        emit to.

        A mount the application refuses undoes the engine step, so a
        failed ``add`` leaves the server as it was.
        """

        graph, spec = self._validate(wf, target, replacing=False)
        name = graph.name
        resolved = self._resolve_pool(pool)
        persisted = self._persist_row(name, target, pool, persist)
        self.engine.register(graph, resolved)
        self._record(name, wf, target, spec)
        if self._serving:
            try:
                self._plugins.add(spec)
            except Exception:
                await self.engine.unregister(name)
                self._forget(name)
                raise
            await recover(self.engine, [name])
            await self._emit(
                EventName.workflow_registered,
                WorkflowRegistered(
                    workflow=name, pool=self._pool_name(name), target=target
                ),
            )
            self.engine.notify()
            _log.info("workflow registered", workflow=name, target=target)
        return Registered(name, persisted)

    async def replace(
        self,
        wf: Workflow,
        pool: str | Pool | None = None,
        *,
        target: str | None = None,
        persist: bool = False,
    ) -> Registered:
        """Swap the registration under ``wf``'s name (22 §Replace).

        The name must be registered (``LoadError``, stage ``register``);
        the graph and the plugins are validated as :meth:`add` validates
        them; with ``persist`` the row is written; then the engine swaps
        the graph — the next claim dispatches on it, an attempt in flight
        finishes on the body it started with — keeping the pool binding
        unless ``pool`` names another, in which case the move is refused
        with ``ValueError`` while any attempt of the workflow is in
        flight (22 §Pools; ``KeyError`` for a pool that does not exist).
        Serving, the old plugin spec is unmounted and the new one mounted
        in its place, ``workflow.replaced`` is emitted, and the scheduler
        is notified. No recovery runs: the name's orphaned rows were
        reset at boot or at its ``add``, and the rows in flight belong to
        attempts still running.

        ``target=None`` keeps the recorded target: a host replacing a
        workflow with an object it built does not lose the record of
        where it first came from.
        """

        graph, spec = self._validate(wf, target, replacing=True)
        name = graph.name
        resolved = self._resolve_pool(pool)
        pool_name = resolved.name if resolved is not None else None
        self._refuse_move_in_flight(name, pool_name)
        recorded = target if target is not None else self._targets[name]
        persisted = self._persist_row(name, recorded, pool, persist)
        await self.engine.replace(graph, pool_name)
        self._workflows[name] = wf
        self._targets[name] = recorded
        self._swap_spec(name, spec)
        if self._serving:
            self._plugins.replace(spec)
            await self._emit(
                EventName.workflow_replaced,
                WorkflowReplaced(
                    workflow=name, pool=self._pool_name(name), target=recorded
                ),
            )
            self.engine.notify()
            _log.info("workflow replaced", workflow=name, target=recorded)
        return Registered(name, persisted)

    async def remove(self, name: str, *, persist: bool = False) -> RemovedWorkflow:
        """Drop the workflow ``name`` (22 §Remove).

        The name must be registered (``LoadError``, stage ``register``).
        With ``persist`` its row is removed first — a name with no row is
        not an error. Then the engine unregisters it: every attempt of
        it this process is running is cancelled the way a shutdown
        cancels, no task status is written, the graph is dropped and the
        name unbound from its pool, which stays. Serving, the plugin
        spec is unmounted and ``workflow.unregistered`` is emitted naming
        the interrupted attempts. Nothing is deleted and nothing is
        notified — nothing became ready.
        """

        if name not in self._workflows:
            message = f"workflow {name!r} is not registered"
            raise LoadError(message, stage="register", target="", detail=message)
        persisted: Path | None = None
        if persist:
            path = self.toml_path
            persisted = path if remove_row(path, name) else None
        task_ids = await self.engine.unregister(name)
        self._forget(name)
        if self._serving:
            self._plugins.remove(name)
            await self._emit(
                EventName.workflow_unregistered,
                WorkflowUnregistered(workflow=name, task_ids=list(task_ids)),
            )
            _log.info("workflow unregistered", workflow=name, task_ids=task_ids)
        return RemovedWorkflow(name, tuple(task_ids), persisted)

    @property
    def workflows(self) -> dict[str, Workflow]:
        """The registered workflows by name, in registration order."""

        return dict(self._workflows)

    @property
    def targets(self) -> dict[str, str | None]:
        """The target each workflow was loaded from, in registration order.

        ``None`` for a programmatic registration (22 §Terms).
        """

        return dict(self._targets)

    @property
    def toml_path(self) -> Path:
        """The ``athanore.toml`` the rows are read from and written to."""

        return self.settings.root_path / TOML_NAME

    # -- what the verbs are made of ----------------------------------------

    @property
    def _serving(self) -> bool:
        """Is there a live application to mount into and a store to emit to?"""

        return self._serve_task is not None and self.app is not None

    @property
    def _plugins(self) -> MountedPlugins:
        """The live application's plugin surface (22 §Live mounting)."""

        app = self.app
        if app is None:  # pragma: no cover - guarded by `_serving`
            raise RuntimeError("the server is not serving")
        plugins: MountedPlugins = app.state.plugins
        return plugins

    def _before_start(self, verb: str) -> None:
        """Refuse a boot-time verb on a serving server (D226)."""

        if self._serve_task is not None:
            raise RuntimeError(
                f"the server is serving; {verb}() is for before start() — "
                f"use add(), replace() or remove()"
            )

    def _finalize(self, wf: Workflow) -> Graph:
        """``wf``'s graph; ``GraphError`` when it does not finalize."""

        return wf.finalize()

    def _check_name(self, name: str, *, replacing: bool = False) -> None:
        """The three name refusals of :meth:`register`, as ``GraphError``.

        ``replacing`` skips the duplicate check — the name is expected
        to be registered — and adds the reverse one.
        """

        if name in RESERVED:
            raise GraphError(
                f"workflow name {name!r} is a CLI verb; workflow names cannot "
                f"shadow verbs (11 §Verbs)"
            )
        if replacing:
            if name not in self._workflows:
                raise GraphError(f"workflow {name!r} is not registered")
            return
        if name in self._workflows:
            raise GraphError(f"workflow {name!r} is already registered")
        if name in self.engine.pools:
            raise GraphError(f"workflow name {name!r} is already the name of a pool")

    def _check_plugins(self, wf: Workflow, graph: Graph) -> PluginSpec:
        """``wf``'s declarations, collected and validated against ``graph``."""

        spec = collect(wf)
        validate(spec, graph)
        return spec

    def _validate(
        self, wf: Workflow, target: str | None, *, replacing: bool
    ) -> tuple[Graph, PluginSpec]:
        """What :meth:`register` checks, each refusal as a :class:`LoadError`.

        The stages 22 §Wire gives the server: ``finalize`` for a graph
        that does not close, ``register`` for a name that is a verb, a
        pool, already registered (``conflict``) or — replacing — not
        registered, ``plugins`` for a declaration that does not validate.
        """

        shown = target if target is not None else ""
        try:
            graph = self._finalize(wf)
        except GraphError as exc:
            raise _load_error(exc, "finalize", shown) from exc
        try:
            self._check_name(graph.name, replacing=replacing)
        except GraphError as exc:
            conflict = not replacing and graph.name in self._workflows
            raise _load_error(exc, "register", shown, conflict=conflict) from exc
        try:
            spec = self._check_plugins(wf, graph)
        except (PluginValidationError, PluginError) as exc:
            raise _load_error(exc, "plugins", shown) from exc
        return graph, spec

    def _resolve_pool(self, pool: str | Pool | None) -> Pool | None:
        """The pool a live verb names, or ``None`` for the default binding.

        A name must be a registered pool — ``KeyError`` naming the known
        ones otherwise (D234; the API's ``422 unknown_pool``). A
        :class:`Pool` object before :meth:`start` is passed through as
        :meth:`register` passes it, the boot-time idiom by which a host
        declares capacity; while serving it contributes only its name
        and must exist, because a live registration never creates or
        resizes a pool (22 §Pools, D233).
        """

        if pool is None:
            return None
        if isinstance(pool, Pool) and self._serve_task is None:
            return pool
        name = pool if isinstance(pool, str) else pool.name
        if name not in self.engine.pools:
            raise KeyError(
                f"no pool named {name!r}; known pools are "
                f"{sorted(state.name for state in self.engine.pools)}"
            )
        return self.engine.pools.get(name).pool

    def _refuse_move_in_flight(self, name: str, pool_name: str | None) -> None:
        """The engine's pool-move refusal, before the row is written.

        :meth:`Engine.replace` makes the authoritative check between
        ticks; this one runs first so that a ``persist=True`` replace
        refused for its pool move has written nothing (22 §Persistence:
        a write happens after every validation).
        """

        if pool_name is None or pool_name == self._pool_name(name):
            return
        live = self.engine.attempts_of(name)
        if live:
            raise ValueError(
                f"workflow {name!r} cannot move from pool "
                f"{self._pool_name(name)!r} to {pool_name!r} with attempts in "
                f"flight: tasks {live}"
            )

    def _pool_name(self, name: str) -> str:
        """The pool ``name`` is bound to, read off the engine."""

        return self.engine.pools.for_workflow(name).name

    def _persist_row(
        self, name: str, target: str | None, pool: str | Pool | None, persist: bool
    ) -> Path | None:
        """Write the row ``persist`` asks for; the path written, or ``None``.

        After every validation and before anything is mutated, so a
        target that does not load is never written down and a write
        that fails (``PersistError``) leaves the server as it was. The
        row carries ``pool`` only when the caller named one — a
        default-pool workflow stays on the default pool if ``workers``
        changes (22 §Persistence). ``persist`` without a target is a
        ``ValueError``: a ``Workflow`` object cannot be written to a file.
        """

        if not persist:
            return None
        if target is None:
            raise ValueError(
                "persist=True needs a target; a Workflow object cannot be "
                "written to athanore.toml"
            )
        path = self.toml_path
        pool_name = pool if isinstance(pool, str) or pool is None else pool.name
        write_row(path, name, target, pool_name)
        return path

    def _record(
        self, name: str, wf: Workflow, target: str | None, spec: PluginSpec
    ) -> None:
        """Hold ``wf`` under ``name``, with its target and its spec.

        A workflow that declares nothing contributes nothing: an empty
        spec would be an empty router and a manifest entry with no
        panels, actions or assets in it (09 §Wire contract). ``_specs``
        is what :meth:`start` hands ``create_app``, so it is kept true
        before and after start alike.
        """

        self._workflows[name] = wf
        self._targets[name] = target
        if spec:
            self._specs.append(spec)

    def _forget(self, name: str) -> None:
        """Drop every record of ``name``."""

        self._workflows.pop(name, None)
        self._targets.pop(name, None)
        self._specs[:] = [spec for spec in self._specs if spec.workflow != name]

    def _swap_spec(self, name: str, spec: PluginSpec) -> None:
        """``spec`` in place of the one held under ``name``.

        At the old one's index; appended when the old was empty and so
        never held; dropped when the new one is empty (D237).
        """

        index = next(
            (i for i, held in enumerate(self._specs) if held.workflow == name), None
        )
        if index is not None:
            del self._specs[index]
        if not spec:
            return
        self._specs.insert(index if index is not None else len(self._specs), spec)

    async def _emit(self, name: EventName, payload: EventModel) -> None:
        """Record one ``workflow.*`` event in its own transaction.

        No ``run_id``: like ``engine.*``, these are about the server (22
        §Events). Stored — they are part of the audit trail and the SSE
        cursor needs their ids — and published to every subscriber by
        the store's outbox.
        """

        async with self.store.uow() as uow:
            uow.emit(
                Event(
                    run_id=None,
                    task_id=None,
                    name=name,
                    data=payload.model_dump(),
                    created=now(),
                )
            )

    # -- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        """Migrate, start the engine, and serve the API.

        Returns once the socket is bound and the application's lifespan
        has run, so a caller may fetch :attr:`url` and use it. Starting a
        server that is already serving is a defect, not a no-op: the
        second call would bind a second port onto the same engine.
        """

        if self._serve_task is not None:
            raise RuntimeError("the server is already started")

        _clear_sse_shutdown_flag()
        configure_logging(self.settings.log_format)
        # Before the database is touched, so a bind nobody could
        # authenticate against fails without having migrated a file.
        check_operator_token(self.settings)
        await self._check_not_v0()
        if self.settings.run_migrations:
            await upgrade(self._db_url)

        self._loop = asyncio.get_running_loop()
        self._stopping = asyncio.Event()
        try:
            await self.engine.start()
            self.app = create_app(
                settings=self.settings,
                engine=self.engine,
                store=self.store,
                plugins=with_builtins(self._specs),
            )
            await self._serve_http(self._bind(self.app))
            self._retention_task = asyncio.create_task(
                self._prune_until_cancelled(), name="athanore-retention"
            )
        except BaseException:
            # A start that failed half way — a port already in use, a
            # plugin the mount refuses — would otherwise leave a dispatch
            # loop claiming work against a store nobody is serving.
            await self.stop()
            raise
        _log.info(
            "serving",
            url=self.url,
            workflows=sorted(self._workflows),
            pools={
                name: pool["capacity"] for name, pool in self.engine.snapshot().items()
            },
        )

    async def stop(self) -> None:
        """Stop the engine, then close the HTTP surface (04 §Shutdown).

        In that order: the attempts are cancelled and ``engine.stopping``
        is written while the API is still answering, and the SSE streams
        close last. Idempotent, and safe on a server that was never
        started.
        """

        if self._stopping is not None:
            self._stopping.set()
        retention, self._retention_task = self._retention_task, None
        if retention is not None:
            retention.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await retention
        await self.engine.stop()
        await self._stop_http()
        self.app = None
        self._bound_port = None
        self._loop = None
        # The pool, not the engine: SQLAlchemy builds a new one on the
        # next connection, so the same object serves the next `start()`.
        await self._sa_engine.dispose()

    def serve(self, on_start: Callable[[Server], None] | None = None) -> None:
        """Serve until stopped. Blocking — 04 §Programmatic host's form.

        Owns the event loop, so it is the entry point of a process rather
        than something to call from inside one. SIGINT and SIGTERM
        request the graceful stop of 04 §Shutdown, which is what makes a
        plain ``kill`` — systemd, ``docker stop``, a supervisor — run the
        engine's shutdown instead of dropping the process on the floor.

        ``on_start`` is called once, with this server, after the socket
        is bound and the application is answering. It exists because
        :attr:`url` is not knowable before that on ``port=0`` and a
        blocking call has no other moment to hand it back:
        ``athanore serve`` prints that URL and ``--open`` points a
        browser at it (11 §Server). A callback that raises stops the
        server rather than leaving it serving something nobody was told
        about.

        It runs on the server's own event loop, so it announces and
        returns: a blocking call *to this server* from inside it would
        wait for a loop that is waiting for the callback.
        """

        asyncio.run(self._serve_until_stopped(on_start))

    def request_stop(self) -> None:
        """Ask a running server to stop, from anywhere.

        Safe from a signal handler, from another thread, and from inside
        the loop itself: uvicorn's exit flag is a plain attribute, and
        the event that ends :meth:`serve` is set through the loop it
        belongs to. Does nothing to a server that is not serving.
        """

        server = self._uvicorn
        if server is not None:
            server.should_exit = True
        loop, stopping = self._loop, self._stopping
        if loop is None or stopping is None or loop.is_closed():
            return
        with contextlib.suppress(RuntimeError):
            loop.call_soon_threadsafe(stopping.set)

    @property
    def url(self) -> str:
        """Where this server can be reached, once it is serving.

        The **bound** port, which is the whole point on ``port=0``, and
        loopback in place of a wildcard bind, because ``0.0.0.0`` is an
        address to listen on rather than one to connect to. What agents
        are told is ``settings.public_url``, which an operator sets for a
        container or a remote agent (12 §S6).
        """

        host = self.settings.host
        if host in _WILDCARD:
            host = "127.0.0.1"
        return f"http://{host}:{self.port}"

    @property
    def port(self) -> int:
        """The port in use: the bound one while serving, else the setting."""

        return self._bound_port if self._bound_port is not None else self.settings.port

    # -- the pieces the lifecycle is made of -------------------------------

    @property
    def _db_url(self) -> str:
        """``settings.db_url``, which the settings validator always fills."""

        db_url = self.settings.db_url
        if db_url is None:  # pragma: no cover - the validator computes it
            raise RuntimeError("settings.db_url is unset")
        return db_url

    async def _check_not_v0(self) -> None:
        """Refuse an MVP database rather than migrating it in place."""

        if not await is_v0_database(self._db_url):
            return
        where = make_url(self._db_url).database or self._db_url
        raise V0Database(
            f"{where} is an athanore v0 database: it has the MVP's `runs` "
            f"table and no `alembic_version`. Migrating it in place would "
            f"strand its history in tables v1 does not read, so it is "
            f"refused. Import it into a fresh v1 database instead — the v0 "
            f"file is opened read-only and never modified:\n"
            f"    mv {where} {where}.v0\n"
            f"    athanore db import-v0 {where}.v0\n"
            f"(07 §Importing a v0 database)"
        )

    def _bind(self, app: FastAPI) -> socket.socket:
        """Take the socket, and learn which port it got.

        Bound here rather than left to ``uvicorn.Server.serve()``,
        because uvicorn answers a port already in use by logging the
        ``OSError`` and calling :func:`sys.exit` — and a ``SystemExit``
        raised inside an :class:`asyncio.Task` is re-raised into the
        event loop, which would tear down the caller's loop instead of
        failing the call they made. In this frame it is an ordinary
        exception, and it becomes the ``OSError`` it stood for.

        ``Config.bind_socket`` is what does the work: uvicorn's IPv6,
        UNIX-socket and file-descriptor cases live there, and this module
        has no business having a second opinion about any of them.
        """

        config = self._uvicorn_config(app)
        self._config = config
        try:
            sock = config.bind_socket()
        except SystemExit as exit_:
            raise OSError(
                f"failed to bind http://{self.settings.host}:{self.settings.port}"
            ) from exit_
        self._bound_port = _socket_port(sock)
        self._adopt_bound_port()
        return sock

    def _uvicorn_config(self, app: FastAPI) -> uvicorn.Config:
        """The uvicorn configuration this server runs ``app`` under."""

        return uvicorn.Config(
            app,
            host=self.settings.host,
            port=self.settings.port,
            # structlog owns stderr, and `configure_logging` has already
            # undone the handlers uvicorn installs from `Config.__init__`.
            log_config=None,
            timeout_graceful_shutdown=int(SHUTDOWN_TIMEOUT),
            # Never "auto": the application's lifespan starts the MCP
            # session manager and the plugin dispatcher, so a lifespan
            # that fails must be an error rather than a downgrade.
            lifespan="on",
        )

    async def _serve_http(self, sock: socket.socket) -> None:
        """Serve on ``sock``, and wait until the application is answering.

        Returns once uvicorn reports ``started`` — set after the server
        is listening and the application's lifespan has run — so a caller
        may use :attr:`url` on return. A serve task that finishes before
        that failed to start, and the exception it holds is the useful
        one.
        """

        config = self._config
        if config is None:  # pragma: no cover - `_bind` runs first and sets it
            raise RuntimeError("the socket was not bound")
        server = _QuietUvicorn(config)
        self._uvicorn = server
        self._serve_task = asyncio.create_task(
            self._run_uvicorn(server, sock), name="athanore-uvicorn"
        )
        try:
            while not server.started:
                if self._serve_task.done():
                    await self._failed_to_start()
                await asyncio.sleep(_BIND_POLL)
        except BaseException:
            # uvicorn closes the sockets it served; one it never got to
            # is this method's to close, or the file descriptor outlives
            # the failed start.
            sock.close()
            raise

    async def _run_uvicorn(self, server: _QuietUvicorn, sock: socket.socket) -> None:
        """``server.serve()``, with its :func:`sys.exit` made catchable.

        uvicorn exits the process when the application's lifespan fails
        to start. A host embedded in somebody else's program does not get
        to do that, and a ``SystemExit`` out of a task would take the
        event loop with it rather than failing :meth:`start`, so it is
        translated where it is raised.
        """

        try:
            await server.serve(sockets=[sock])
        except SystemExit as exit_:
            raise OSError(
                f"uvicorn stopped during startup (exit status {exit_.code})"
            ) from exit_

    async def _failed_to_start(self) -> None:
        """Re-raise what the serve task holds, or say that it holds nothing."""

        task, self._serve_task = self._serve_task, None
        self._uvicorn = None
        if task is not None:
            await task
        raise OSError(
            f"uvicorn stopped before it served http://{self.settings.host}:"
            f"{self.settings.port}"
        )

    def _adopt_bound_port(self) -> None:
        """Tell the rest of the process which port an ephemeral bind got.

        ``port=0`` leaves ``settings.public_url`` pointing at port 0,
        which is the base URL every agent and every MCP session would be
        handed (04 §TaskContext). The bound port is the only true answer,
        so it replaces the placeholder — and only when the URL is the one
        the settings derived, never one the operator wrote themselves
        (12 §S6 exists because that URL is theirs to set).
        """

        bound = self._bound_port
        if bound is None or bound == self.settings.port:
            return
        derived = f"http://{self.settings.host}:{self.settings.port}"
        if self.settings.public_url == derived:
            self.settings.public_url = f"http://{self.settings.host}:{bound}"
        self.settings.port = bound

    async def _stop_http(self) -> None:
        """Ask uvicorn to exit and wait for it, within the budget.

        Shielded, so a caller cancelled while stopping still leaves the
        serve task to finish its own shutdown rather than tearing the
        connections down mid-response.
        """

        server, self._uvicorn = self._uvicorn, None
        task, self._serve_task = self._serve_task, None
        self._config = None
        if server is not None:
            server.should_exit = True
        if task is None or task.done():
            return
        try:
            await asyncio.wait_for(asyncio.shield(task), SHUTDOWN_TIMEOUT)
        except TimeoutError:
            _log.error("uvicorn did not shut down in time", budget_s=SHUTDOWN_TIMEOUT)
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _prune_until_cancelled(self) -> None:
        """Run the retention job for as long as the server serves.

        A pass that fails ends the loop by design (07 §Retention: a
        janitor that swallowed its own failures would look alive while
        the database grew), so the failure is logged where an operator
        will see it. It does not stop the server: retention is
        housekeeping, and a server that stopped serving because a delete
        failed would lose work over a chore.
        """

        try:
            await retention_loop(self.store, self.settings.retention)
        except asyncio.CancelledError:
            raise
        except Exception:
            _log.exception("the retention loop stopped; history will not be pruned")

    async def _serve_until_stopped(
        self, on_start: Callable[[Server], None] | None = None
    ) -> None:
        """What :meth:`serve` runs: start, announce, wait, stop.

        The wait ends on a signal, on :meth:`request_stop`, or on uvicorn
        exiting by itself — a socket lost, a lifespan that failed — so a
        server that has stopped answering does not leave the process
        sitting on a loop that nothing will ever wake.
        """

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            # Not every loop or platform has them, and a loop running off
            # the main thread never does; the caller stops such a server
            # with `request_stop()`.
            with contextlib.suppress(NotImplementedError, RuntimeError, ValueError):
                loop.add_signal_handler(sig, self.request_stop)
        await self.start()
        stopping = self._stopping
        serving = self._serve_task
        try:
            if on_start is not None:
                on_start(self)
            if stopping is not None and serving is not None:
                waiter = asyncio.ensure_future(stopping.wait())
                try:
                    await asyncio.wait(
                        (waiter, serving), return_when=asyncio.FIRST_COMPLETED
                    )
                finally:
                    # uvicorn may have been the one to finish; the waiter
                    # is this loop's and is cancelled either way.
                    waiter.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await waiter
        finally:
            for sig in (signal.SIGINT, signal.SIGTERM):
                with contextlib.suppress(NotImplementedError, RuntimeError, ValueError):
                    loop.remove_signal_handler(sig)
            await self.stop()

    def __repr__(self) -> str:
        state = "serving" if self._serve_task is not None else "stopped"
        return f"<Server {sorted(self._workflows)} {state} at {self.url}>"


def _clear_sse_shutdown_flag() -> None:
    """Undo the process-global "we are shutting down" `sse-starlette` sets.

    ``sse_starlette.sse.AppStatus.should_exit`` is a **class attribute**,
    not per-application state, and once it is true every
    ``EventSourceResponse`` built afterwards ends immediately. It is set
    by a watcher the library runs for the duration of each open stream,
    which polls the uvicorn server it finds on the ``SIGTERM`` handler —
    and :meth:`Server._stop_http` sets that server's ``should_exit`` to
    ask for the graceful shutdown 04 §Shutdown wants.

    So a server that was serving an event stream when it stopped leaves
    the flag set, and the *next* server in the same process serves an
    event stream that closes the moment it opens. :meth:`Server.start`
    supports being called again after :meth:`Server.stop` — a
    programmatic host restarting, a test suite reusing one server — and
    an SSE feed that silently stops working after the first restart is
    exactly the kind of "half started" this class exists to prevent.

    Clearing it here is safe because it is scoped to a start: a shutdown
    signal that arrives afterwards sets it again, and one that arrived
    while this method was running would be reported by
    :meth:`Server.request_stop`, which is what the signal handlers 04
    §Shutdown installs actually call.
    """

    AppStatus.should_exit = False


def _socket_port(sock: socket.socket) -> int | None:
    """The port ``sock`` is bound to, or ``None`` if it has no port.

    A UNIX socket's name is a path, not an address, so there is no port
    to report and none is invented (02 §Real data only).
    """

    address: Any = sock.getsockname()
    if isinstance(address, tuple) and len(address) >= 2:
        return int(address[1])
    return None


def _load_error(
    exc: Exception, stage: LoadStage, target: str, *, conflict: bool = False
) -> LoadError:
    """A refusal of the server's, as the one exception type 22 §Wire names."""

    return LoadError(
        str(exc), stage=stage, target=target, detail=str(exc), conflict=conflict
    )


def _pool_of(layout: Layout, name: str, path: Path) -> Pool | None:
    """The pool a ``[workflows.<name>]`` row binds, or ``None`` for the default.

    A pool ``[pools]`` does not declare is refused with the sentence
    ``athanore serve`` prints for any binding it cannot honour.
    """

    bound = layout.bindings.get(name)
    if bound is None:
        return None
    if bound not in layout.pools:
        raise LayoutError(
            path,
            f"workflow `{name}` is bound to pool `{bound}`, which `[pools]` in "
            f"{path} does not declare.",
        )
    return Pool(bound, layout.pools[bound])


#: The MVP's name for the host, kept for one minor version (14
#: §Compatibility).
AthanoreServer = Server

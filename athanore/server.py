"""The programmatic host: settings, store, engine, API and uvicorn (04
§Programmatic host).

.. code-block:: python

    server = Server()                       # settings from env / athanore.toml
    server.register(feature_build, Pool("local", 1))
    server.serve()                          # blocking
    # ...or `await server.start()` / `await server.stop()` in a test

This is the composition root and nothing else. Every object it wires
together already exists and already knows how to do its job; what lives
here is the *order* they are built in, and the two refusals that keep a
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
from typing import Any

import uvicorn
from fastapi import FastAPI
from sqlalchemy.engine import make_url

from athanore.api.app import create_app
from athanore.api.deps import check_operator_token
from athanore.cli.verbs import RESERVED
from athanore.engine import SHUTDOWN_BUDGET, Engine, Pool
from athanore.events.bus import EventBus
from athanore.graph import GraphError
from athanore.logging import configure_logging, get_logger
from athanore.plugins.builtin import with_builtins
from athanore.plugins.registry import PluginSpec, collect, validate
from athanore.requests.service import RequestService
from athanore.settings import AthanoreSettings
from athanore.store.engine import make_engine
from athanore.store.migrate import is_v0_database, upgrade
from athanore.store.retention import retention_loop
from athanore.store.uow import Store
from athanore.workflow import Workflow

__all__ = ["AthanoreServer", "Server", "V0Database"]

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
        self._specs: list[PluginSpec] = []
        self._config: uvicorn.Config | None = None
        self._uvicorn: _QuietUvicorn | None = None
        self._serve_task: asyncio.Task[None] | None = None
        self._retention_task: asyncio.Task[None] | None = None
        self._stopping: asyncio.Event | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._bound_port: int | None = None

    # -- registration ------------------------------------------------------

    def register(self, wf: Workflow, pool: Pool | None = None) -> Server:
        """Finalize ``wf``, check its name, and run it on ``pool``.

        Three names must not collide, and all three are checked here
        rather than at the moment the collision would be felt:

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

        Returns the server, so registrations chain.
        """

        graph = wf.finalize()
        name = graph.name
        if name in RESERVED:
            raise GraphError(
                f"workflow name {name!r} is a CLI verb; workflow names cannot "
                f"shadow verbs (11 §Verbs)"
            )
        if name in self._workflows:
            raise GraphError(f"workflow {name!r} is already registered")
        if name in self.engine.pools:
            raise GraphError(f"workflow name {name!r} is already the name of a pool")
        spec = collect(wf)
        validate(spec, graph)
        # Last, because it is the only step that mutates anything: a
        # refusal above leaves the server exactly as it was.
        self.engine.register(graph, pool)
        self._workflows[name] = wf
        # A workflow that declares nothing contributes nothing: an empty
        # spec would be an empty router and a manifest entry with no
        # panels, actions or assets in it (09 §Wire contract).
        if spec:
            self._specs.append(spec)
        return self

    @property
    def workflows(self) -> dict[str, Workflow]:
        """The registered workflows by name, in registration order."""

        return dict(self._workflows)

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

    def serve(self) -> None:
        """Serve until stopped. Blocking — 04 §Programmatic host's form.

        Owns the event loop, so it is the entry point of a process rather
        than something to call from inside one. SIGINT and SIGTERM
        request the graceful stop of 04 §Shutdown, which is what makes a
        plain ``kill`` — systemd, ``docker stop``, a supervisor — run the
        engine's shutdown instead of dropping the process on the floor.
        """

        asyncio.run(self._serve_until_stopped())

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

    async def _serve_until_stopped(self) -> None:
        """What :meth:`serve` runs: start, wait, stop.

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


def _socket_port(sock: socket.socket) -> int | None:
    """The port ``sock`` is bound to, or ``None`` if it has no port.

    A UNIX socket's name is a path, not an address, so there is no port
    to report and none is invented (02 §Real data only).
    """

    address: Any = sock.getsockname()
    if isinstance(address, tuple) and len(address) >= 2:
        return int(address[1])
    return None


#: The MVP's name for the host, kept for one minor version (14
#: §Compatibility).
AthanoreServer = Server

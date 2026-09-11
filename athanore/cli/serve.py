"""``athanore serve``: the one verb that is not an API client (11 §Server).

Every other verb asks a running server a question over HTTP. This one
*is* the server: it resolves the workflows to run, reads the pools they
run on, and hands both to :class:`athanore.server.Server`, which is the
composition root. Nothing is orchestrated here — the wiring is 04
§Programmatic host's and belongs to that class. What lives in this module
is the part a command line has and a library call does not:

- **Where a workflow comes from.** Three inputs, one precedence (22
  §Persistence): each positional target — ``module:attr`` or
  ``path/to/file.py:attr``, resolved by
  :func:`athanore.plugins.discovery.load_target` through the
  :func:`load_target` wrapper here — then the ``[workflows.<name>]``
  rows of ``athanore.toml`` that carry a ``target``, through
  :meth:`athanore.server.Server.register_configured`, then what the
  installed distributions advertise (09 §Discovery) through
  :func:`discovered`, unless ``--no-discover`` says not to. A positional
  wins over a row of the same name (the row is skipped with a warning
  naming both targets) and a positional or a row wins over a discovered
  workflow (the discovered one is dropped). Every workflow's target is
  recorded on the server, so ``athanore workflows reload <name>`` can
  reload what ``serve`` loaded.
- **Where the pools come from.** :func:`layout` reads ``[pools]`` and
  ``[workflows]`` out of ``athanore.toml`` (02 §``athanore.toml``
  layout), through :func:`athanore.plugins.discovery.read_layout`. They
  are not settings — ``AthanoreSettings`` ignores both tables — because
  they name objects the host builds rather than values it holds.
- **What the operator is told.** The bound URL is printed *after* the
  socket exists, which is the whole point on ``--port 0``: the port a
  server picked is knowable nowhere else, and ``--open`` points a browser
  at that same string.

The heavy imports are made inside the command body, exactly as
:meth:`athanore.workflow.Workflow.run` makes its own: ``athanore db``,
``athanore token`` and ``athanore login`` are repair verbs that must keep
working on an installation whose server cannot even be built, and pulling
uvicorn, the API and the store in to parse ``athanore token show`` would
make that impossible.
"""

from __future__ import annotations

import webbrowser
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

import typer

from athanore.cli import app
from athanore.cli.output import EXIT_API_ERROR, EXIT_USAGE, fail, warn
from athanore.settings import AthanoreSettings

if TYPE_CHECKING:  # the deferred imports of the command body, for the types
    from athanore.engine import Pool
    from athanore.plugins.discovery import Discovered
    from athanore.server import Server
    from athanore.workflow import Workflow

__all__ = ["announce", "layout", "load_target", "serve"]


def discovered() -> list[Discovered]:
    """The workflows installed packages advertise, each with its target.

    The group, the ``module:attr``-or-callable form of an entry and the
    refusal of one that is neither belong to
    :mod:`athanore.plugins.discovery`; what belongs here is only that
    ``serve`` asks for them at all, and the import is written inside the
    body for the reason the module docstring gives — ``athanore token
    show`` must not import a workflow, a graph and pydantic to parse a
    flag.

    The precedence between what this returns and what the operator typed
    is applied in :func:`serve`, on the *workflow's* name rather than the
    entry point's: the left-hand side of an entry is what the
    distribution called it, and the name a run is submitted under is the
    workflow's own. The target recorded for a discovered workflow is the
    entry point's ``module:attr`` value (22 §Terms).
    """

    from athanore.plugins.discovery import discover

    return discover()


def load_target(target: str) -> Workflow:
    """The workflow ``target`` names (11 §Server).

    :func:`athanore.plugins.discovery.load_target` does the work — the
    loader lives beside the entry-point loader so the API can reach it
    without importing the CLI (22 §Reloading a module). What is decided
    here is the price: every failure is a mistake in what was typed — a
    module that is not importable, a file that is not there, an
    attribute that is not a workflow — so every one of them is a
    :class:`typer.BadParameter`, which 11 §Exit codes prices at 2.
    """

    from athanore.plugins.discovery import LoadError
    from athanore.plugins.discovery import load_target as load

    try:
        return load(target)
    except LoadError as exc:
        raise typer.BadParameter(str(exc)) from exc


def layout(root_path: Path) -> tuple[dict[str, int], dict[str, str]]:
    """``[pools]`` and ``[workflows]`` from ``athanore.toml`` (02).

    Returns the declared capacities by pool name and the pool each
    workflow is bound to, read through
    :func:`athanore.plugins.discovery.read_layout` — the one reader of
    the two tables, which ``Server.register_configured`` reads the
    ``target`` rows through as well. A file that says something the
    reader cannot use is a :class:`typer.BadParameter` here, for the
    reason 02 gives for an unknown top-level key: a typo must not
    silently fall back to a default.
    """

    from athanore.plugins.discovery import LayoutError, read_layout

    try:
        read = read_layout(root_path / "athanore.toml")
    except LayoutError as exc:
        raise typer.BadParameter(str(exc)) from exc
    return read.pools, read.bindings


def _pool_for(
    name: str,
    bindings: dict[str, str],
    capacities: dict[str, int],
    root_path: Path,
) -> Pool | None:
    """The pool workflow ``name`` runs on, or ``None`` for the default one."""

    from athanore.engine import Pool

    bound = bindings.get(name)
    if bound is None:
        return None
    if bound not in capacities:
        raise typer.BadParameter(
            f"workflow `{name}` is bound to pool `{bound}`, which "
            f"`[pools]` in {root_path / 'athanore.toml'} does not declare."
        )
    try:
        return Pool(bound, capacities[bound])
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


def _sentence(exc: Exception) -> str:
    """``exc`` as the line to print: a ``KeyError`` without its quotes."""

    if isinstance(exc, KeyError) and exc.args:
        return str(exc.args[0])
    return str(exc)


def _settings(**overrides: Any) -> AthanoreSettings:
    """Settings with the flags the operator actually gave on top.

    Only the ones they gave: a flag left at its default is not an
    instruction to override the environment or ``athanore.toml`` with
    typer's idea of a default, and passing ``None`` through would do
    exactly that for every field the operator did not name.
    """

    given = {name: value for name, value in overrides.items() if value is not None}
    try:
        return AthanoreSettings(**given)
    except ValueError as exc:
        # Both refusals are one: pydantic's `ValidationError` and
        # pydantic-settings' `SettingsError` — which is what an unknown
        # key in `athanore.toml` raises — are both `ValueError`s, and
        # each already carries the sentence naming the field.
        raise typer.BadParameter(str(exc)) from exc


def announce(server: Server, *, open_browser: bool) -> None:
    """Say where the server is, and point a browser at it if asked.

    Called once the socket is bound, so the URL is the real one on
    ``--port 0``. Printed with the builtin rather than through a rich
    console: this line is read by whatever started the process, and a
    console would decide for itself whether to flush it.

    The browser is pointed at the same string that was printed rather
    than at one built a second time, which is what makes ``--open`` on
    an ephemeral port land on the server that is actually running.
    """

    url = server.url
    names = sorted(server.workflows)
    print(f"Athanore is serving on {url}", flush=True)
    print(f"workflows: {', '.join(names) if names else 'none registered'}", flush=True)
    if open_browser:
        webbrowser.open(url)


@app.command()
def serve(
    targets: Annotated[
        list[str] | None,
        typer.Argument(
            metavar="[TARGET]...",
            help="Workflows to run, as `module:wf` or `path/to/file.py:wf`.",
        ),
    ] = None,
    host: Annotated[
        str | None,
        typer.Option("--host", help="Interface to bind. Defaults to 127.0.0.1."),
    ] = None,
    port: Annotated[
        int | None,
        typer.Option("--port", help="Port to bind; 0 picks a free one."),
    ] = None,
    workers: Annotated[
        int | None,
        typer.Option("--workers", help="Capacity of the default pool."),
    ] = None,
    db: Annotated[
        str | None,
        typer.Option("--db", metavar="URL", help="Database URL to serve."),
    ] = None,
    no_discover: Annotated[
        bool,
        typer.Option("--no-discover", help="Do not register entry-point workflows."),
    ] = False,
    public_url: Annotated[
        str | None,
        typer.Option(
            "--public-url",
            metavar="URL",
            help="The URL agents and MCP sessions are told to call back on.",
        ),
    ] = None,
    open_browser: Annotated[
        bool,
        typer.Option("--open", help="Open the SPA in a browser once it is serving."),
    ] = False,
) -> None:
    """Run a server for the given workflows until it is stopped."""

    from athanore.graph import GraphError
    from athanore.plugins.discovery import DiscoveryError, LayoutError, LoadError
    from athanore.server import MissingOperatorToken, Server, V0Database

    settings = _settings(
        host=host,
        port=port,
        workers=workers,
        db_url=db,
        public_url=public_url,
    )
    # The positionals are loaded before the file is read, so a mistyped
    # target is reported before a mistyped table — the order the
    # operator wrote them in.
    loaded = [(target, load_target(target)) for target in targets or []]
    capacities, bindings = layout(settings.root_path)
    toml_path = settings.root_path / "athanore.toml"
    server = Server(settings)

    def register(wf: Workflow, target: str) -> None:
        pool = _pool_for(wf.name, bindings, capacities, settings.root_path)
        try:
            server.register(wf, pool, target=target)
        except (GraphError, ValueError, TypeError) as exc:
            # A name that shadows a verb or a pool, a graph that does not
            # finalize, a declaration that names a node it does not have.
            fail(str(exc))
            raise typer.Exit(EXIT_API_ERROR) from exc

    # 1. The positionals, each recorded under the target as it was typed
    #    (22 §Terms), so `athanore workflows reload <name>` can reload it.
    for target, wf in loaded:
        register(wf, target)
    # 2. The `[workflows.<name>].target` rows (22 §Persistence): a row is a
    #    positional written down, loaded through the same loader and
    #    priced the same (exit 2) when it fails. A positional of the same
    #    name has already won; the row is skipped with a warning.
    try:
        rows = server.register_configured()
    except (LoadError, LayoutError, GraphError, ValueError, KeyError) as exc:
        fail(_sentence(exc))
        raise typer.Exit(EXIT_USAGE) from exc
    for skipped in rows.skipped:
        warn(
            f"`[workflows.{skipped.name}]` in {toml_path} names "
            f"{skipped.target}, but {skipped.name!r} is already registered from "
            f"{skipped.registered}; the row was skipped."
        )
    # 3. What the installed distributions advertise, minus every name a
    #    positional or a row already registered: an explicit target wins
    #    over a discovered workflow of the same name, because the operator
    #    naming a file means that file (09 §Discovery).
    if not no_discover:
        try:
            advertised = discovered()
        except DiscoveryError as exc:
            # An installed package that advertises a workflow it cannot
            # produce (09 §Discovery). Not a usage error — nothing was
            # mistyped — and not something to skip past either, so it is
            # the sentence naming the entry point and an exit. The way
            # on, until the package is fixed, is `--no-discover`.
            fail(str(exc))
            raise typer.Exit(EXIT_API_ERROR) from exc
        named = set(server.workflows)
        # Against the names registered so far only, not against each
        # other: two distributions advertising one name are a collision
        # the registration refuses, not a precedence to apply.
        for found in advertised:
            if found.workflow.name not in named:
                register(found.workflow, found.target)
    for name in sorted(set(bindings) - set(server.workflows)):
        # Said once, and not fatal: a project's `athanore.toml` describes
        # every workflow it has, and serving one of them on purpose is
        # ordinary. A binding that was silently not applied is what would
        # not be.
        warn(
            f"`[workflows.{name}]` in {settings.root_path / 'athanore.toml'} "
            f"names a workflow this server does not run; its pool binding "
            f"was not applied."
        )

    try:
        server.serve(
            on_start=lambda started: announce(started, open_browser=open_browser)
        )
    except (MissingOperatorToken, V0Database, OSError) as exc:
        # The three ways a correctly typed command still cannot serve: a
        # network bind with no operator token (12 §Operator token), an
        # MVP database awaiting `db import-v0` (07), and a port already
        # in use. Each carries the sentence the operator needs, and a
        # traceback would bury it.
        fail(str(exc))
        raise typer.Exit(EXIT_API_ERROR) from exc

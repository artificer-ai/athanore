"""``athanore serve``: the one verb that is not an API client (11 §Server).

Every other verb asks a running server a question over HTTP. This one
*is* the server: it resolves the workflows to run, reads the pools they
run on, and hands both to :class:`athanore.server.Server`, which is the
composition root. Nothing is orchestrated here — the wiring is 04
§Programmatic host's and belongs to that class. What lives in this module
is the part a command line has and a library call does not:

- **Where a workflow comes from.** :func:`load_target` resolves the
  ``module:attr`` and ``path/to/file.py:attr`` forms of 11 §Server. A
  file target is executed as a module with its own directory on
  ``sys.path``, which is what ``python that_file.py`` would have done, so
  a workflow that imports its siblings keeps working when it is named on
  a command line instead of run. :func:`discovered` asks the installed
  distributions for the rest (09 §Discovery), unless ``--no-discover``
  says not to, and a target the operator typed wins over a discovered
  workflow of the same name.
- **Where the pools come from.** :func:`layout` reads ``[pools]`` and
  ``[workflows]`` out of ``athanore.toml`` (02 §``athanore.toml``
  layout). They are not settings — ``AthanoreSettings`` ignores both
  tables — because they name objects the host builds rather than values
  it holds.
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

import importlib
import importlib.util
import os
import sys
import tomllib
import webbrowser
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

import typer

from athanore.cli import app
from athanore.cli.output import EXIT_API_ERROR, fail, warn
from athanore.settings import AthanoreSettings

if TYPE_CHECKING:  # the deferred imports of the command body, for the types
    from athanore.engine import Pool
    from athanore.server import Server
    from athanore.workflow import Workflow

__all__ = ["announce", "layout", "load_target", "serve"]

#: The one key ``[workflows.<name>]`` takes (02 §``athanore.toml``
#: layout). Anything else is a typo, and a typo that silently did nothing
#: would put a workflow on the wrong pool for as long as nobody looked.
WORKFLOW_KEYS = frozenset({"pool"})


def discovered() -> list[Workflow]:
    """The workflows installed packages advertise (09 §Discovery).

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
    workflow's own.
    """

    from athanore.plugins.discovery import discover

    return discover()


def load_target(target: str) -> Workflow:
    """The workflow ``target`` names (11 §Server).

    ``package.module:wf`` imports the module; ``path/to/file.py:wf``
    executes the file. Both forms end at an attribute, because a module
    may define several workflows and picking one by guessing would be a
    rule nobody could read off the command line.

    Every failure here is a mistake in what was typed — a module that is
    not importable, a file that is not there, an attribute that is not a
    workflow — so every one of them is a :class:`typer.BadParameter`,
    which 11 §Exit codes prices at 2.
    """

    from athanore.workflow import Workflow

    where, separator, attribute = target.rpartition(":")
    if not separator or not where or not attribute:
        raise typer.BadParameter(
            f"{target!r} is not a workflow target; name one as `module:wf` "
            f"or `path/to/file.py:wf`."
        )
    module = _load_module(where, target)
    try:
        value = getattr(module, attribute)
    except AttributeError:
        raise typer.BadParameter(
            f"{where} has no attribute {attribute!r} ({target})."
        ) from None
    if not isinstance(value, Workflow):
        raise typer.BadParameter(
            f"{target} is a {type(value).__name__}, not a Workflow."
        )
    return value


def _load_module(where: str, target: str) -> Any:
    """Import the module half of a target, from the path or from the name."""

    if where.endswith(".py") or os.sep in where or (os.altsep and os.altsep in where):
        return _load_file(Path(where), target)
    # A console script does not put the working directory on `sys.path`
    # the way `python -m` does, so `athanore serve mypkg.flows:wf` in a
    # project directory would not find the project without this.
    _prepend_sys_path(Path.cwd())
    try:
        return importlib.import_module(where)
    except ImportError as exc:
        raise typer.BadParameter(f"{target} could not be imported: {exc}") from exc


def _load_file(path: Path, target: str) -> Any:
    """Execute ``path`` as a module and return it.

    The file's own directory goes on ``sys.path`` first, so a workflow
    that imports a sibling module resolves it the way it would if the
    file had been run directly. The module is registered in
    ``sys.modules`` before it is executed, because a dataclass, a pydantic
    model or a pickle defined in it looks itself up there by name — and
    it is removed again if the execution fails, so a half-built module is
    never left behind for the next import to find.
    """

    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise typer.BadParameter(f"{target} names {resolved}, which is not a file.")
    spec = importlib.util.spec_from_file_location(resolved.stem, resolved)
    if spec is None or spec.loader is None:  # pragma: no cover - a `.py` always has one
        raise typer.BadParameter(f"{resolved} cannot be imported as a module.")
    _prepend_sys_path(resolved.parent)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(spec.name, None)
        raise
    return module


def _prepend_sys_path(directory: Path) -> None:
    """Put ``directory`` first on ``sys.path``, once."""

    entry = str(directory)
    if entry not in sys.path:
        sys.path.insert(0, entry)


def layout(root_path: Path) -> tuple[dict[str, int], dict[str, str]]:
    """``[pools]`` and ``[workflows]`` from ``athanore.toml`` (02).

    Returns the declared capacities by pool name and the pool each
    workflow is bound to. Neither table is a setting — ``AthanoreSettings``
    skips both, because they describe objects the host builds rather than
    values it holds — so the file is read a second time here, resolved
    against ``root_path`` exactly as the settings source resolves it.

    A file that is not there is not an error: a server with one workflow
    on the default pool needs no configuration at all. A file that is
    there and says something this cannot use is refused where it can be
    fixed, for the reason 02 gives for an unknown top-level key: a typo
    must not silently fall back to a default.
    """

    toml_path = root_path / "athanore.toml"
    if not toml_path.is_file():
        return {}, {}
    try:
        with toml_path.open("rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise typer.BadParameter(f"{toml_path} could not be read: {exc}") from exc
    return _pools(data.get("pools", {}), toml_path), _bindings(
        data.get("workflows", {}), toml_path
    )


def _pools(table: Any, toml_path: Path) -> dict[str, int]:
    """``[pools]`` as capacities by name."""

    if not isinstance(table, dict):
        raise typer.BadParameter(f"`[pools]` in {toml_path} must be a table.")
    capacities: dict[str, int] = {}
    for name, capacity in table.items():
        # `bool` is an `int` in Python and `local = true` is a typo, not
        # a cap of one — the same refusal `Pool` makes of its own field.
        if type(capacity) is not int:
            raise typer.BadParameter(
                f"pool `{name}` in {toml_path} must be an integer capacity, "
                f"got {capacity!r}."
            )
        capacities[str(name)] = capacity
    return capacities


def _bindings(table: Any, toml_path: Path) -> dict[str, str]:
    """``[workflows]`` as the pool name each workflow asked for.

    A workflow with an empty table (``msgtest = { }`` in 02's example)
    names no pool and is left to the engine's default one, so it is
    absent from the result rather than present with a name nobody wrote.
    """

    if not isinstance(table, dict):
        raise typer.BadParameter(f"`[workflows]` in {toml_path} must be a table.")
    bindings: dict[str, str] = {}
    for name, entry in table.items():
        if not isinstance(entry, dict):
            raise typer.BadParameter(
                f"`[workflows.{name}]` in {toml_path} must be a table, got {entry!r}."
            )
        unknown = sorted(set(entry) - WORKFLOW_KEYS)
        if unknown:
            raise typer.BadParameter(
                f"unknown key `{unknown[0]}` in `[workflows.{name}]` of "
                f"{toml_path} (it takes `pool` and nothing else)."
            )
        pool = entry.get("pool")
        if pool is None:
            continue
        if not isinstance(pool, str):
            raise typer.BadParameter(
                f"`pool` in `[workflows.{name}]` of {toml_path} must be a "
                f"pool name, got {pool!r}."
            )
        bindings[str(name)] = pool
    return bindings


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
    from athanore.plugins.discovery import DiscoveryError
    from athanore.server import MissingOperatorToken, Server, V0Database

    settings = _settings(
        host=host,
        port=port,
        workers=workers,
        db_url=db,
        public_url=public_url,
    )
    workflows = [load_target(target) for target in targets or []]
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
        named = {wf.name for wf in workflows}
        # An explicit target wins over a discovered workflow of the same
        # name: the operator naming a file means that file (09 §Discovery).
        workflows.extend(wf for wf in advertised if wf.name not in named)
    capacities, bindings = layout(settings.root_path)

    server = Server(settings)
    for wf in workflows:
        pool = _pool_for(wf.name, bindings, capacities, settings.root_path)
        try:
            server.register(wf, pool)
        except (GraphError, ValueError, TypeError) as exc:
            # A name that shadows a verb or a pool, a graph that does not
            # finalize, a declaration that names a node it does not have.
            fail(str(exc))
            raise typer.Exit(EXIT_API_ERROR) from exc
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

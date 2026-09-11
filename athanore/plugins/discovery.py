"""Where a workflow comes from: a target, an entry point, a row of
``athanore.toml`` (09 §Discovery, 11 §Server, 22 §Reloading a module).

Three inputs name the workflows a server runs, and this module resolves
all three, because they are one list with a precedence rather than three
mechanisms (22 §Persistence):

- **A target** — ``package.module:attr`` or ``path/to/file.py:attr`` —
  is what ``athanore serve`` takes on its command line, what a
  ``[workflows.<name>].target`` row writes down, and what the API takes
  on request. :func:`load_target` resolves one, and with ``reload=True``
  resolves it a *second* time in one process, which is the case a live
  ``replace`` exists for: a module target purges its own subtree from
  ``sys.modules`` first, a file target executes afresh, and
  :mod:`linecache` is invalidated for every file involved so ``inspect``
  reads the text the process now runs (22 §Reloading a module, D224).
- **An entry point** in the ``athanore.workflows`` group is what an
  installed distribution contributes:

  ```toml
  [project.entry-points."athanore.workflows"]
  feature_build = "acme.flows:feature_build"
  gamedev       = "acme.flows:build_gamedev"       # a callable returning one
  ```

  :func:`discover` loads every entry and pairs each workflow with the
  entry's ``module:attr`` value — the target a reload of a discovered
  workflow re-resolves (22 §Terms).
- **The tables of ``athanore.toml``** — ``[pools]`` and ``[workflows]``
  — are read by :func:`read_layout`. They are not settings:
  ``AthanoreSettings`` skips both, because they name objects the host
  builds rather than values it holds (02 §``athanore.toml`` layout).

Two things about the entry-point group are decided here, because they
are the two an operator only ever learns by being surprised.

**The entry point's name is not the workflow's name.** The left-hand side
is what the distribution called the entry; the name a run is submitted
under is the ``Workflow``'s own, which is the only name the engine, the
API and ``athanore.toml``'s ``[workflows]`` table know. They are usually
the same string and nothing requires it, so the precedence
``athanore serve`` applies — an explicit target beats a discovered
workflow of the same name (11 §Server) — is applied to the *workflow's*
name. The same rule holds for a target: the name it resolves to is the
``Workflow``'s own, not the target's.

**A broken entry point is refused, not skipped.** Loading one runs the
installing package's code, and every way it can go wrong — a module that
will not import, an attribute that is not there, a value that is not a
``Workflow``, a factory that raised — is that package being broken rather
than the operator having mistyped something. Skipping it would start a
server missing a workflow whose absence is next observed as a 404 on a
name that is definitely installed, so :func:`discover` raises
:class:`DiscoveryError` naming the entry and the distribution it came
from, ``athanore serve`` prints that sentence and exits, and
``--no-discover`` is the way past a package that cannot be fixed today.

A target that fails is a :class:`LoadError` naming the **stage** it
stopped at (22 §Wire), because the caller — an agent, more often than
not — is the one who has to fix the file and try again. The loader
raises ``target``, ``import`` and ``attribute``; the server's live verbs
raise ``finalize``, ``plugins`` and ``register`` with the same type, so
one exception says where any registration stopped.

This module sits in no tier of 02 §Layering and imports only
:mod:`athanore.workflow`, so the CLI and the API can both reach it.
Nothing from ``engine``, ``server``, ``cli`` or ``api`` belongs here.
"""

from __future__ import annotations

import importlib
import importlib.util
import linecache
import os
import sys
import tomllib
from dataclasses import dataclass
from importlib.metadata import EntryPoint, entry_points
from pathlib import Path
from typing import Any, Literal

from athanore.workflow import Workflow

__all__ = [
    "GROUP",
    "WORKFLOW_KEYS",
    "Discovered",
    "DiscoveryError",
    "Layout",
    "LayoutError",
    "LoadError",
    "LoadStage",
    "Registered",
    "RemovedWorkflow",
    "UnknownPool",
    "discover",
    "load_target",
    "read_layout",
]

#: The entry-point group 09 §Discovery names. One group, fixed: an
#: installed package is discovered because it declared itself here, and
#: nothing else on the machine is imported to find out.
GROUP = "athanore.workflows"

#: The keys ``[workflows.<name>]`` takes (02 §``athanore.toml`` layout,
#: 22 §Persistence). Anything else is a typo, and a typo that silently did
#: nothing would put a workflow on the wrong pool — or leave one
#: unregistered — for as long as nobody looked.
WORKFLOW_KEYS = frozenset({"pool", "target"})

#: Where a registration stopped (22 §Wire). The first three are the
#: loader's; the last three are the server's, raised with the same
#: exception so the API can report any of the six in one body.
LoadStage = Literal["target", "import", "attribute", "finalize", "plugins", "register"]


class DiscoveryError(Exception):
    """An advertised entry point that is not a workflow.

    Carries the sentence the operator acts on — which entry, in which
    distribution, and what went wrong — because the fix is to repair or
    uninstall a package, and neither is possible from "discovery failed".
    """


class LoadError(Exception):
    """A target that did not become a registered workflow (22 §Wire).

    ``str(exc)`` is ``message``, the one sentence the operator or the
    agent reads. ``stage`` is where it stopped; ``target`` is the string
    that was being loaded (``""`` for a programmatic object the server's
    verbs refused); ``detail`` is the underlying error's full text,
    untouched — for ``target``, where there is no underlying error, it is
    the message again. ``conflict`` marks the two refusals the wire
    answers 409 rather than 422: ``Server.add`` sets it on a name that
    is already registered, and ``Server.reload_target`` on a target whose
    workflow is not the one named in the URL — so the API can tell them
    apart without parsing text.
    """

    def __init__(
        self,
        message: str,
        *,
        stage: LoadStage,
        target: str,
        detail: str,
        conflict: bool = False,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.stage: LoadStage = stage
        self.target = target
        self.detail = detail
        self.conflict = conflict


class UnknownPool(KeyError):
    """A live registration named a pool the engine does not have (22 §Pools).

    A ``KeyError``, as the server's verbs have always raised for one
    (D234, D239), with the pool that was asked for and the pools that
    exist as attributes; ``str(exc)`` is the sentence naming both, which
    is what the API's ``422 unknown_pool`` and ``athanore serve``'s exit
    2 both print. Pools are never removed while serving, so the engine's
    own ``KeyError`` for a pool that vanished between the server's check
    and its own cannot happen; this is the one type a caller has to
    catch.
    """

    def __init__(self, pool: str, known: tuple[str, ...]) -> None:
        super().__init__(f"no pool named {pool!r}; known pools are {list(known)}")
        self.pool = pool
        self.known = known

    def __str__(self) -> str:
        # `KeyError.__str__` reprs its one argument, which would wrap the
        # sentence in quotes; the sentence is the message.
        return str(self.args[0])


class LayoutError(Exception):
    """``athanore.toml``'s ``[pools]`` or ``[workflows]`` cannot be used.

    02: a typo must not silently fall back to a default. ``str(exc)`` is
    the sentence ``athanore serve`` prints; ``path`` is the file.
    """

    def __init__(self, path: Path, detail: str) -> None:
        super().__init__(detail)
        self.path = path
        self.detail = detail


@dataclass(frozen=True)
class Discovered:
    """One discovered workflow and the target that re-resolves it."""

    workflow: Workflow
    #: The entry point's ``module:attr`` value (22 §Terms).
    target: str


@dataclass(frozen=True)
class Registered:
    """What ``Server.add`` and ``Server.replace`` did (22 §Server surface).

    ``persisted`` is the ``athanore.toml`` the row was written to, or
    ``None`` when no file was touched.
    """

    name: str
    persisted: Path | None


@dataclass(frozen=True)
class RemovedWorkflow:
    """What ``Server.remove`` did (22 §Server surface).

    ``task_ids`` are the attempts it interrupted, in spawn order —
    what ``workflow.unregistered`` announces. ``persisted`` is the
    ``athanore.toml`` the row was removed from, or ``None``.
    """

    workflow: str
    task_ids: tuple[int, ...]
    persisted: Path | None


@dataclass(frozen=True)
class Layout:
    """``[pools]`` and ``[workflows]`` of one ``athanore.toml``.

    ``pools`` is capacity by pool name; ``bindings`` is name → pool for
    every row that names one; ``targets`` is name → target for every row
    that has one, in the file's order — each of those rows is a
    registration (22 §Persistence).
    """

    pools: dict[str, int]
    bindings: dict[str, str]
    targets: dict[str, str]


class _NotAWorkflow(Exception):
    """A value that is neither a ``Workflow`` nor a factory yielding one.

    Private: each caller wraps it in its own type with its own sentence,
    because the fix for a broken entry point (repair the package) and
    the fix for a mistyped target (fix the string) are different.
    """


# --------------------------------------------------------------------------
# Entry points
# --------------------------------------------------------------------------


def discover() -> list[Discovered]:
    """Every workflow the installed distributions advertise, with its target.

    Entries are loaded in a fixed order — by entry-point name, then by
    value — so two installations with the same packages register the same
    workflows in the same order, and a collision between two
    distributions that advertise the same workflow name is refused the
    same way every time rather than resolved by whichever the file system
    happened to yield first.

    Raises :class:`DiscoveryError` for the first entry that does not
    yield a workflow.
    """

    found = entry_points(group=GROUP)
    return [
        Discovered(_workflow(entry), entry.value)
        for entry in sorted(found, key=lambda e: (e.name, e.value))
    ]


def _workflow(entry: EntryPoint) -> Workflow:
    """The workflow ``entry`` names, or a :class:`DiscoveryError`.

    ``module:attr`` is the form 09 gives, and the attribute may be the
    workflow itself or a callable returning one — a factory, so a package
    can build its graph out of its own settings at serve time instead of
    at import time. Nothing else is accepted: a value that is neither is
    a declaration pointing at the wrong name, which is worth saying with
    the type it actually found.
    """

    try:
        value = entry.load()
    except Exception as exc:
        raise DiscoveryError(f"{_where(entry)} could not be loaded: {exc}") from exc
    try:
        return _resolve(value, _where(entry))
    except _NotAWorkflow as exc:
        raise DiscoveryError(str(exc)) from exc.__cause__


def _resolve(value: Any, describe: str) -> Workflow:
    """``value`` as a workflow: itself, or what it returns when called.

    Shared by the entry-point path and the target path, because a
    discovered workflow's recorded target is its entry point's value and
    reloading it has to accept what discovery accepted (22 §Reloading a
    module). ``describe`` is how the caller's sentence names the value.
    """

    if isinstance(value, Workflow):
        return value
    if callable(value):
        try:
            built = value()
        except Exception as exc:
            raise _NotAWorkflow(f"{describe} raised when called: {exc}") from exc
        if isinstance(built, Workflow):
            return built
        raise _NotAWorkflow(
            f"{describe} is a callable that returned a "
            f"{type(built).__name__}, not a Workflow."
        )
    raise _NotAWorkflow(f"{describe} is a {type(value).__name__}, not a Workflow.")


def _where(entry: EntryPoint) -> str:
    """The entry as it is written, and the distribution that wrote it.

    ``EntryPoint.dist`` is set on everything ``entry_points()`` returns
    and unset on one built by hand, so it is read defensively: the name
    of the package to uninstall is the useful half of this sentence and
    its absence must not turn a message into an ``AttributeError``.
    """

    written = f"`{entry.name} = {entry.value}` in group {GROUP!r}"
    dist = entry.dist
    if dist is None:
        return f"entry point {written}"
    return f"entry point {written}, from {dist.name} {dist.version}"


# --------------------------------------------------------------------------
# Targets
# --------------------------------------------------------------------------


def load_target(target: str, *, reload: bool = False) -> Workflow:
    """The workflow ``target`` names (11 §Server, 22 §Reloading a module).

    ``package.module:wf`` imports the module; ``path/to/file.py:wf``
    executes the file. Both forms end at an attribute, because a module
    may define several workflows and picking one by guessing would be a
    rule nobody could read off the command line. The attribute may be
    the workflow or a callable returning one, as an entry point's value
    may (09 §Discovery).

    With ``reload``, the target is loaded again in a process that already
    imported it: a module target's whole subtree — ``where`` and every
    ``where.*`` — is dropped from ``sys.modules`` first and imported
    afresh, a file target is executed again into a new module object
    that replaces the old one under the file's stem, and ``linecache`` is
    invalidated for every file involved so ``inspect.getsource`` shows
    the text the process now runs. A sibling module, and a helper the
    target imports from outside its own subtree, are not reloaded (22
    §Scope, D224). A load that fails leaves ``sys.modules`` as the
    failure found it: the file's half-built module is removed, and a
    module target's purge is not undone — the next successful load fixes
    the cache, and the old module objects the running attempts hold are
    unaffected by what ``sys.modules`` says.

    Every failure is a :class:`LoadError` naming its stage: ``target``
    for a string that is not ``where:attr``, ``import`` for a module or
    file that would not load, ``attribute`` for one that is not there,
    is not a ``Workflow``, or is a factory that raised.
    """

    where, separator, attribute = target.rpartition(":")
    if not separator or not where or not attribute:
        message = (
            f"{target!r} is not a workflow target; name one as `module:wf` "
            f"or `path/to/file.py:wf`."
        )
        raise LoadError(message, stage="target", target=target, detail=message)
    stale = _purge(where) if reload else []
    module = _load_module(where, target)
    for path in [*stale, getattr(module, "__file__", None)]:
        if path:
            linecache.checkcache(path)
    try:
        value = getattr(module, attribute)
    except AttributeError as exc:
        raise LoadError(
            f"{where} has no attribute {attribute!r} ({target}).",
            stage="attribute",
            target=target,
            detail=str(exc),
        ) from None
    try:
        return _resolve(value, target)
    except _NotAWorkflow as exc:
        cause = exc.__cause__
        raise LoadError(
            str(exc),
            stage="attribute",
            target=target,
            detail=str(cause) if cause is not None else str(exc),
        ) from cause


def _is_file_target(where: str) -> bool:
    """Is the module half of a target a path rather than a dotted name?"""

    return bool(
        where.endswith(".py") or os.sep in where or (os.altsep and os.altsep in where)
    )


def _purge(where: str) -> list[str]:
    """Drop a module target's subtree from ``sys.modules`` (22, D224).

    Returns the ``__file__`` of every module dropped, for the linecache.
    Every key equal to ``where`` or beginning with ``where.`` goes, and
    nothing else: ``workflows.feature`` takes ``workflows.feature.agents``
    with it and leaves ``workflows.rps`` alone. ``importlib.reload`` alone
    would re-execute one module and leave its submodules cached, which is
    the "I edited the file and nothing changed" every author of a
    reloader has met once. A file target has no subtree — its stem is
    replaced by the load itself — so only its old file is collected.

    The finder's directory caches are invalidated too: a submodule
    written since the first import is otherwise invisible to it.
    """

    if _is_file_target(where):
        stem = Path(where).expanduser().resolve().stem
        old = sys.modules.get(stem)
        path = getattr(old, "__file__", None) if old is not None else None
        return [path] if path else []
    prefix = where + "."
    files: list[str] = []
    for name in [key for key in sys.modules if key == where or key.startswith(prefix)]:
        module = sys.modules.pop(name)
        path = getattr(module, "__file__", None)
        if path:
            files.append(path)
    importlib.invalidate_caches()
    return files


def _load_module(where: str, target: str) -> Any:
    """Import the module half of a target, from the path or from the name.

    Anything the import raises is stage ``import`` — an ``ImportError``
    from user code, a ``SyntaxError`` in the file, a module-level
    exception — because each is "the module or file would not load".
    """

    if _is_file_target(where):
        return _load_file(Path(where), target)
    # A console script does not put the working directory on `sys.path`
    # the way `python -m` does, so `athanore serve mypkg.flows:wf` in a
    # project directory would not find the project without this.
    _prepend_sys_path(Path.cwd())
    try:
        return importlib.import_module(where)
    except Exception as exc:
        raise LoadError(
            f"{target} could not be imported: {exc}",
            stage="import",
            target=target,
            detail=str(exc),
        ) from exc


def _load_file(path: Path, target: str) -> Any:
    """Execute ``path`` as a module and return it.

    The file's own directory goes on ``sys.path`` first, so a workflow
    that imports a sibling module resolves it the way it would if the
    file had been run directly. The module is registered in
    ``sys.modules`` before it is executed, because a dataclass, a pydantic
    model or a pickle defined in it looks itself up there by name — and
    it is removed again if the execution fails, so a half-built module is
    never left behind for the next import to find. Executed afresh on
    every call: a second load of the same file is a new module object
    under the same stem (22 §Reloading a module).
    """

    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        message = f"{target} names {resolved}, which is not a file."
        raise LoadError(message, stage="import", target=target, detail=message)
    spec = importlib.util.spec_from_file_location(resolved.stem, resolved)
    if spec is None or spec.loader is None:  # pragma: no cover - a `.py` always has one
        message = f"{resolved} cannot be imported as a module."
        raise LoadError(message, stage="import", target=target, detail=message)
    _prepend_sys_path(resolved.parent)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException as exc:
        sys.modules.pop(spec.name, None)
        if not isinstance(exc, Exception):
            raise
        raise LoadError(
            f"{target} could not be imported: {exc}",
            stage="import",
            target=target,
            detail=str(exc),
        ) from exc
    return module


def _prepend_sys_path(directory: Path) -> None:
    """Put ``directory`` first on ``sys.path``, once."""

    entry = str(directory)
    if entry not in sys.path:
        sys.path.insert(0, entry)


# --------------------------------------------------------------------------
# athanore.toml
# --------------------------------------------------------------------------


def read_layout(toml_path: Path) -> Layout:
    """``[pools]`` and ``[workflows]`` from ``athanore.toml`` (02, 22).

    Neither table is a setting — ``AthanoreSettings`` skips both, because
    they describe objects the host builds rather than values it holds —
    so the file is read here, at the path the settings source resolves
    (``root_path / athanore.toml``).

    A file that is not there is not an error: a server with one workflow
    on the default pool needs no configuration at all. A file that is
    there and says something this cannot use is refused where it can be
    fixed, for the reason 02 gives for an unknown top-level key: a typo
    must not silently fall back to a default.
    """

    if not toml_path.is_file():
        return Layout({}, {}, {})
    try:
        with toml_path.open("rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise LayoutError(toml_path, f"{toml_path} could not be read: {exc}") from exc
    pools = _pools(data.get("pools", {}), toml_path)
    bindings, targets = _rows(data.get("workflows", {}), toml_path)
    return Layout(pools, bindings, targets)


def _pools(table: Any, toml_path: Path) -> dict[str, int]:
    """``[pools]`` as capacities by name."""

    if not isinstance(table, dict):
        raise LayoutError(toml_path, f"`[pools]` in {toml_path} must be a table.")
    capacities: dict[str, int] = {}
    for name, capacity in table.items():
        # `bool` is an `int` in Python and `local = true` is a typo, not
        # a cap of one — the same refusal `Pool` makes of its own field.
        if type(capacity) is not int:
            raise LayoutError(
                toml_path,
                f"pool `{name}` in {toml_path} must be an integer capacity, "
                f"got {capacity!r}.",
            )
        capacities[str(name)] = capacity
    return capacities


def _rows(table: Any, toml_path: Path) -> tuple[dict[str, str], dict[str, str]]:
    """``[workflows]`` as the pool each row asked for, and the target each has.

    A workflow with an empty table (``msgtest = { }`` in 02's example)
    names no pool and is left to the engine's default one, so it is
    absent from the bindings rather than present with a name nobody
    wrote; a row with no ``target`` is a binding only, not a
    registration (22 §Persistence).
    """

    if not isinstance(table, dict):
        raise LayoutError(toml_path, f"`[workflows]` in {toml_path} must be a table.")
    bindings: dict[str, str] = {}
    targets: dict[str, str] = {}
    for name, entry in table.items():
        if not isinstance(entry, dict):
            raise LayoutError(
                toml_path,
                f"`[workflows.{name}]` in {toml_path} must be a table, got {entry!r}.",
            )
        unknown = sorted(set(entry) - WORKFLOW_KEYS)
        if unknown:
            raise LayoutError(
                toml_path,
                f"unknown key `{unknown[0]}` in `[workflows.{name}]` of "
                f"{toml_path} (it takes `pool` and `target` and nothing else).",
            )
        pool = entry.get("pool")
        if pool is not None:
            if not isinstance(pool, str):
                raise LayoutError(
                    toml_path,
                    f"`pool` in `[workflows.{name}]` of {toml_path} must be a "
                    f"pool name, got {pool!r}.",
                )
            bindings[str(name)] = pool
        target = entry.get("target")
        if target is not None:
            if not isinstance(target, str) or not _is_target(target):
                raise LayoutError(
                    toml_path,
                    f"`target` in `[workflows.{name}]` of {toml_path} must name "
                    f"a workflow as `module:wf` or `path/to/file.py:wf`, "
                    f"got {target!r}.",
                )
            targets[str(name)] = target
    return bindings, targets


def _is_target(target: str) -> bool:
    """Is ``target`` of the ``where:attr`` shape :func:`load_target` takes?"""

    where, separator, attribute = target.rpartition(":")
    return bool(separator and where and attribute)

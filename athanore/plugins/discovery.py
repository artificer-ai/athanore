"""The workflows an installation advertises (09 §Discovery).

A workflow does not have to be named on a command line to be served. A
distribution that installs one declares it in the ``athanore.workflows``
entry-point group, and ``athanore serve`` registers every entry it finds:

```toml
[project.entry-points."athanore.workflows"]
feature_build = "acme.flows:feature_build"
gamedev       = "acme.flows:build_gamedev"       # a callable returning one
```

Two things about that group are decided here, because they are the two
an operator only ever learns by being surprised.

**The entry point's name is not the workflow's name.** The left-hand side
is what the distribution called the entry; the name a run is submitted
under is the ``Workflow``'s own, which is the only name the engine, the
API and ``athanore.toml``'s ``[workflows]`` table know. They are usually
the same string and nothing requires it, so the precedence
``athanore serve`` applies — an explicit target beats a discovered
workflow of the same name (11 §Server) — is applied to the *workflow's*
name.

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
"""

from __future__ import annotations

from importlib.metadata import EntryPoint, entry_points

from athanore.workflow import Workflow

__all__ = ["GROUP", "DiscoveryError", "discover"]

#: The entry-point group 09 §Discovery names. One group, fixed: an
#: installed package is discovered because it declared itself here, and
#: nothing else on the machine is imported to find out.
GROUP = "athanore.workflows"


class DiscoveryError(Exception):
    """An advertised entry point that is not a workflow.

    Carries the sentence the operator acts on — which entry, in which
    distribution, and what went wrong — because the fix is to repair or
    uninstall a package, and neither is possible from "discovery failed".
    """


def discover() -> list[Workflow]:
    """Every workflow the installed distributions advertise.

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
        _workflow(entry) for entry in sorted(found, key=lambda e: (e.name, e.value))
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
    if isinstance(value, Workflow):
        return value
    if callable(value):
        try:
            built = value()
        except Exception as exc:
            raise DiscoveryError(f"{_where(entry)} raised when called: {exc}") from exc
        if isinstance(built, Workflow):
            return built
        raise DiscoveryError(
            f"{_where(entry)} is a callable that returned a "
            f"{type(built).__name__}, not a Workflow."
        )
    raise DiscoveryError(
        f"{_where(entry)} is a {type(value).__name__}, not a Workflow."
    )


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

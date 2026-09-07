"""What a workflow declares to extend the UI and the API (09 §Declarations).

Four declarations and nothing else: a :class:`Route` is a path operation
mounted under the workflow's own prefix, an :class:`Action` is a named
handler whose pydantic model *is* its form, a :class:`Panel` is data
describing a pane the browser renders, and a :class:`Handler` subscribes
to the event vocabulary. They are inert records — a name, some metadata
and, for three of the four, the function the author wrote. Nothing here
imports FastAPI, the store or the engine: turning a declaration into a
live route is :mod:`athanore.plugins.mount`'s job, and validating a set
of them against a finalized graph is :mod:`athanore.plugins.registry`'s.

That split is what keeps ``Workflow`` cheap to import. An author's module
declares its plugin surface at import time, and a tool that only wants to
*read* a workflow — the CLI listing it, a test finalizing it — pays for
none of the server.

``panel`` is a plain call rather than a decorator (D50): it declares data
and has no function to wrap. The earlier draft decorated a function it
never called, which read as if the body mattered.

:class:`PluginError` lives here because it is the one exception a
*handler* raises, so it belongs beside the declarations a handler is
attached to rather than in the module that mounts them — and because
:mod:`athanore.api.errors` renders it, which it can only do by importing
from a layer below itself (02 §Layering).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel

__all__ = [
    "METHODS",
    "PLACEMENTS",
    "Action",
    "Handler",
    "Panel",
    "PanelKind",
    "Placement",
    "PluginError",
    "Route",
    "Scope",
    "Slot",
]

#: The HTTP methods a plugin route may declare. Every method FastAPI can
#: mount but ``TRACE``, which no browser client of this API speaks.
METHODS: frozenset[str] = frozenset(
    {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
)


class Slot(StrEnum):
    """Where a panel is shown — 09 §Slots, one member per row.

    ``run`` is a pane in the selected run's cycle or a card on its
    overview, ``task`` the task drawer, ``node`` a pane live only while
    the named node has a task in flight or has produced output,
    ``workflow`` the library's detail side, and ``global`` a pane shown
    when no run is selected.
    """

    run = "run"
    task = "task"
    node = "node"
    workflow = "workflow"
    # `global` is a keyword; the *value* is what the wire and the SPA see.
    global_ = "global"


#: What a declaration needs resolved before it runs, in the same five
#: words as :class:`Slot`. The vocabularies coincide because they are the
#: same question asked twice — a pane in the run slot is answered with a
#: run — and 09 gives an action the slot names as its scopes. Spelled as
#: an alias rather than a second enum so a `scope` and a `slot` compare
#: equal instead of merely reading alike.
Scope = Slot


class PanelKind(StrEnum):
    """The renderer vocabulary of 09 §Panel kinds, one member per row.

    The kind fixes the shape ``source`` must return: ``markdown`` a
    string, ``kv`` an object, ``table`` ``{columns, rows}``, ``log`` a
    list of entries, ``chart`` ``{series, kind}``, ``dashboard``
    ``{note?, metrics, table?}``, ``form`` the name of an action, and
    ``custom`` nothing at all — the plugin's own web component reads what
    it needs through ``window.athanore``.

    A kind the SPA does not know renders a placeholder card rather than
    crashing the pane (09), so this enum is the server's vocabulary and
    not a promise about the browser's.
    """

    markdown = "markdown"
    kv = "kv"
    table = "table"
    log = "log"
    chart = "chart"
    dashboard = "dashboard"
    form = "form"
    custom = "custom"


#: Where a ``run``-slot panel goes: its own pane in the run's cycle, or a
#: card appended to the overview pane (09 §Slots). A `Literal` rather
#: than a third enum — 09 names two values and the task names two enums,
#: and a two-valued vocabulary that no other module branches on is a type,
#: not a namespace.
Placement = Literal["pane", "card"]

#: Both placements, for the registry's coercion and the tests' benefit.
PLACEMENTS: frozenset[str] = frozenset({"pane", "card"})


class PluginError(Exception):
    """What a plugin handler raises to answer with a status of its own.

    ``raise PluginError(404, "no such word")`` inside a route, an action
    or an ``on`` handler is reported as the error shape of 08
    §Conventions with ``code: "plugin_error"`` and this status — see
    :data:`athanore.api.errors.DOMAIN_ERRORS`. It is also what the
    context itself raises when a handler reaches for something its scope
    does not have (09 §Context and scopes: ``PluginError(400, "no run in
    scope")``), because a service that returned ``None`` instead would
    fail later, somewhere the plugin author cannot place.
    """

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        #: The HTTP status this refusal is reported with.
        self.status = status
        #: The human half of the error body.
        self.message = message

    def __repr__(self) -> str:
        return f"PluginError({self.status}, {self.message!r})"


@dataclass(frozen=True)
class Route:
    """One path operation, mounted under ``/api/plugins/{workflow}``.

    ``path`` is relative to that prefix and starts with ``/``. The
    handler takes ``ctx: PluginContext`` — resolved from the ``run_id`` /
    ``task_id`` / ``node`` query parameters — and any other parameter it
    declares follows ordinary FastAPI rules, so a route may take a
    ``limit: int = 50`` and get it parsed and documented for free.
    """

    path: str
    methods: tuple[str, ...]
    fn: Callable[..., Any]

    def __post_init__(self) -> None:
        if not self.path.startswith("/"):
            raise ValueError(
                f"a plugin route's path is relative to /api/plugins/<workflow> "
                f"and must start with '/': {self.path!r}"
            )
        if not self.methods:
            raise ValueError(f"route {self.path!r} declares no HTTP method")
        unknown = sorted(set(self.methods) - METHODS)
        if unknown:
            raise ValueError(
                f"route {self.path!r} declares {unknown}, which "
                f"{'are' if len(unknown) > 1 else 'is'} not among "
                f"{sorted(METHODS)}"
            )


@dataclass(frozen=True)
class Action:
    """A named handler, its form, and what it needs resolved to run.

    ``model`` is the pydantic model the request's ``input`` is validated
    against, and it is the form the SPA renders: 09's "the model **is**
    the form". It is read off the handler's ``input`` parameter unless
    the author names one explicitly, so the type annotation an author
    already wrote is the declaration. ``None`` means the action takes no
    input at all.

    ``confirm`` asks the SPA for a confirmation dialog before the call.
    It is advice to the browser, not a server-side check: an action that
    must not run twice enforces that in its handler.
    """

    name: str
    title: str
    scope: Scope
    confirm: bool
    model: type[BaseModel] | None
    fn: Callable[..., Any]


@dataclass(frozen=True)
class Panel:
    """A pane, declared as data (09 §Panel kinds, §Slots).

    ``source`` is where the data comes from: one of this workflow's
    routes for the data kinds, or one of its actions for ``form``. It may
    be given as the function itself — which is what an author has to hand
    — or as the route's path or the action's name.

    ``element`` is the custom element tag a ``custom`` panel renders, and
    is required for that kind and meaningless for any other.

    ``node`` names the node a ``node``-slot panel follows. Liveness is
    computed server-side and travels on the per-run graph response, so
    the manifest stays static and the SPA decides from the graph whether
    to show the pane (08 §Graph semantics).

    ``refresh_on`` are event-name globs; the SPA refetches ``source``
    when one of them arrives on the feed.
    """

    name: str
    slot: Slot
    placement: Placement
    kind: PanelKind
    scope: Scope
    node: str | None = None
    source: Callable[..., Any] | str | None = None
    element: str | None = None
    refresh_on: tuple[str, ...] = ()


@dataclass(frozen=True)
class Handler:
    """One ``on`` subscription: an event name, and what to call with it.

    ``event`` is a name from the vocabulary of 03 or one of this
    workflow's own ``plugin.<workflow>.<name>`` events; the registry
    refuses anything else at registration. The handler is called after
    the transaction that emitted the event has committed, and an
    exception it raises is logged and dropped (09 §Wire contract).
    """

    event: str
    fn: Callable[..., Any]


@dataclass
class Declarations:
    """The four lists a :class:`~athanore.workflow.Workflow` accumulates.

    A record rather than four attributes on ``Workflow`` so that the
    object an author decorates and the object the registry reads are the
    same shape, and so ``collect`` has one thing to copy.
    """

    routes: list[Route] = field(default_factory=list)
    actions: list[Action] = field(default_factory=list)
    panels: list[Panel] = field(default_factory=list)
    handlers: list[Handler] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.routes or self.actions or self.panels or self.handlers)


def coerce_methods(methods: str | Sequence[str] | None) -> tuple[str, ...]:
    """``methods=`` as the uppercase tuple :class:`Route` stores.

    ``None`` is ``("GET",)`` — 09's "``methods=`` defaults to GET" — and
    a bare string is the one method it names, so ``methods="POST"`` means
    what it looks like rather than five one-letter methods.
    """

    if methods is None:
        return ("GET",)
    if isinstance(methods, str):
        return (methods.upper(),)
    return tuple(method.upper() for method in methods)


def coerce_placement(placement: str) -> Placement:
    """``placement=`` as the literal, or a ``ValueError`` naming both values."""

    if placement not in PLACEMENTS:
        raise ValueError(
            f"placement must be one of {sorted(PLACEMENTS)}, got {placement!r}"
        )
    # Narrowed by the membership test above; `Placement` is a two-value
    # literal and `str` does not narrow to it on its own.
    return "pane" if placement == "pane" else "card"

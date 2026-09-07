"""Collecting a workflow's declarations, checking them, publishing them.

09 §Registration and validation. Three functions and one record:
:func:`collect` freezes what a :class:`~athanore.workflow.Workflow`
accumulated into a :class:`PluginSpec`, :func:`validate` refuses a spec
that cannot work, and :func:`manifest_entry` renders the one the SPA
reads.

**Errors at startup, never at runtime** — the same contract the graph
has. A panel pointing at a route nobody declared, an ``on`` naming an
event that does not exist, a ``custom`` panel with no element: each of
them is a pane that renders empty or a subscriber that never fires, and
each is silent. The six checks below are what turns all of them into a
:class:`PluginValidationError` at ``server.register(wf)``, where the
author is still looking.

The six, in the order :func:`validate` runs them:

1. **Duplicate names** — two routes on one path and method, two actions
   or two panels with one name.
2. **A node that does not exist** — a panel's ``node``, and a panel whose
   slot or scope is ``node`` and which names none.
3. **A ``custom`` panel with no ``element``** — there is no tag to render.
4. **A ``source`` that names nothing** — a data panel must name one of
   this workflow's routes, a ``form`` panel one of its actions.
5. **An ``assets`` directory that does not exist.**
6. **An ``on`` outside the vocabulary** — a name 03 does not define, or a
   ``plugin.*`` name in another workflow's namespace.

09 states five of them in one sentence and the fourth in its table
("``source`` (a route)", and "an action name" for the ``form`` kind);
17 §T049 asks for six, and the ``source`` check is the sixth (D138).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from athanore.events.names import PLUGIN_PREFIX, is_known
from athanore.graph import Graph
from athanore.plugins.decl import Action, Handler, Panel, PanelKind, Route, Slot
from athanore.workflow import Workflow

__all__ = [
    "BUILTIN_WORKFLOW",
    "PluginSpec",
    "PluginValidationError",
    "collect",
    "manifest_entry",
    "validate",
]

#: The workflow name the core-shipped plugins are published under (09
#: §Builtins are plugins, T050). It is not a registered workflow: no run
#: has it, its declarations apply to every run, and the leading
#: underscore is what keeps it out of the space of names a user workflow
#: may take (`cli.verbs.RESERVED`, T051).
BUILTIN_WORKFLOW = "_builtin"

#: Where a plugin's static assets are served from (09 §Escape hatch).
ASSETS_URL = "/plugins/{workflow}/static"

#: Where a plugin's routes are mounted (08 §Plugins).
ROUTES_URL = "/api/plugins/{workflow}"


class PluginValidationError(ValueError):
    """A declaration this server refuses to publish.

    Raised by :func:`validate` and by nothing else, so a host that
    registers workflows in a loop can name the workflow that failed.
    A ``ValueError`` because that is what a bad argument is, and
    ``server.register(wf)`` is where the argument was passed.
    """


@dataclass(frozen=True)
class PluginSpec:
    """One workflow's plugin surface, frozen.

    What :func:`collect` produces and everything downstream reads: the
    router :func:`athanore.plugins.mount.mount` builds, the manifest
    :func:`manifest_entry` renders, and the subscriptions
    :func:`athanore.plugins.mount.dispatch_handlers` makes.

    ``assets`` and ``base`` are kept apart rather than joined here
    because 09 resolves a relative ``assets=`` against the *declaring
    module*, and a host serving package data may hand :func:`validate` a
    different root (an installed wheel's extracted data). :meth:`assets_dir`
    is the one place the two are put together.
    """

    workflow: str
    routes: tuple[Route, ...] = ()
    actions: tuple[Action, ...] = ()
    panels: tuple[Panel, ...] = ()
    handlers: tuple[Handler, ...] = ()
    assets: str | Path | None = None
    base: Path = Path()

    def assets_dir(self, root: Path | None = None) -> Path | None:
        """The declared assets directory, resolved, or ``None``.

        An absolute ``assets=`` is itself; a relative one is resolved
        against ``root`` when a host supplies one, and against
        :attr:`base` — the module that declared the workflow — otherwise.
        """

        if self.assets is None:
            return None
        declared = Path(self.assets)
        if declared.is_absolute():
            return declared
        return ((root if root is not None else self.base) / declared).resolve()

    @property
    def prefix(self) -> str:
        """The URL prefix this workflow's routes are mounted under."""

        return ROUTES_URL.format(workflow=self.workflow)

    def route_for(self, fn: Callable[..., Any]) -> Route | None:
        """The route declared for ``fn``, if one was."""

        return next((route for route in self.routes if route.fn is fn), None)

    def action_for(self, fn: Callable[..., Any]) -> Action | None:
        """The action declared for ``fn``, if one was."""

        return next((action for action in self.actions if action.fn is fn), None)

    def action_named(self, name: str) -> Action | None:
        """The action called ``name``, if this workflow declares one."""

        return next((action for action in self.actions if action.name == name), None)

    def __bool__(self) -> bool:
        """Whether this workflow declares anything at all."""

        return bool(
            self.routes
            or self.actions
            or self.panels
            or self.handlers
            or self.assets is not None
        )


def collect(workflow: Workflow) -> PluginSpec:
    """Freeze ``workflow``'s declarations into a :class:`PluginSpec`.

    A copy, in declaration order: the spec is what the server holds for
    the life of the process, and a workflow that kept accumulating
    declarations behind it would have a manifest nothing validated.
    ``Workflow`` refuses a declaration after ``finalize()`` for the same
    reason.
    """

    declarations = workflow.declarations
    return PluginSpec(
        workflow=workflow.name,
        routes=tuple(declarations.routes),
        actions=tuple(declarations.actions),
        panels=tuple(declarations.panels),
        handlers=tuple(declarations.handlers),
        assets=workflow.assets,
        base=workflow.assets_base,
    )


def validate(spec: PluginSpec, graph: Graph, assets_root: Path | None = None) -> None:
    """Refuse ``spec`` if it cannot work, naming what is wrong.

    ``graph`` is the finalized graph of the workflow the spec belongs to,
    which is what makes check 2 possible; ``assets_root`` overrides the
    directory a relative ``assets=`` resolves against, for a host serving
    a package's data from somewhere other than the module's own
    directory.

    Raises :class:`PluginValidationError` on the first failure, with the
    whole of what is wrong in the message.
    """

    _check_duplicates(spec)
    _check_nodes(spec, graph)
    _check_elements(spec)
    _check_sources(spec)
    _check_assets(spec, assets_root)
    _check_handlers(spec)


def manifest_entry(spec: PluginSpec, assets_root: Path | None = None) -> dict[str, Any]:
    """``spec`` as one entry of ``GET /api/plugins`` (09 §Wire contract).

    ``{workflow, panels, actions, assets}``. A panel carries its slot,
    placement, kind and scope, the node it follows when it follows one,
    the URL its data comes from (or, for a ``form``, the action name),
    the element tag a ``custom`` panel renders, and the event globs that
    invalidate it. An action carries the JSON Schema of its model —
    which *is* its form — so the SPA renders one without a second
    declaration.

    Fields that do not apply are **absent**, not null: 01 §Real data only
    is the rule the whole API is written to, and a ``source`` of ``null``
    on a ``custom`` panel is a value the client has to know to ignore.

    Call it after :func:`validate`. Nothing here re-checks: a ``source``
    that names nothing has already been refused, so the manifest is a
    rendering, not a second opinion.
    """

    return {
        "workflow": spec.workflow,
        "panels": [_panel_entry(spec, panel) for panel in spec.panels],
        "actions": [_action_entry(action) for action in spec.actions],
        "assets": _asset_urls(spec, assets_root),
    }


def _panel_entry(spec: PluginSpec, panel: Panel) -> dict[str, Any]:
    """One panel of the manifest."""

    entry: dict[str, Any] = {
        "name": panel.name,
        "slot": panel.slot.value,
        "placement": panel.placement,
        "kind": panel.kind.value,
        "scope": panel.scope.value,
        "refresh_on": list(panel.refresh_on),
    }
    if panel.node is not None:
        entry["node"] = panel.node
    source = _source_ref(spec, panel)
    if source is not None:
        entry["source"] = source
    if panel.element is not None:
        entry["element"] = panel.element
    return entry


def _action_entry(action: Action) -> dict[str, Any]:
    """One action of the manifest, with its form."""

    return {
        "name": action.name,
        "title": action.title,
        "scope": action.scope.value,
        "confirm": action.confirm,
        "schema": _action_schema(action),
    }


def _action_schema(action: Action) -> dict[str, Any]:
    """The JSON Schema of an action's input model.

    An action with no model takes no input, and says so in the schema
    language the SPA already speaks: an object with no properties renders
    as a form with nothing but its submit button.
    """

    if action.model is None:
        return {"type": "object", "title": action.title, "properties": {}}
    return action.model.model_json_schema()


def _source_ref(spec: PluginSpec, panel: Panel) -> str | None:
    """What a panel's ``source`` is on the wire.

    The mounted URL of the route it names, or — for a ``form`` panel —
    the name of the action, because that is what the SPA looks the form
    up by (09 §Panel kinds). ``None`` when the panel declares no source,
    which is every ``custom`` panel and any static one.
    """

    source = panel.source
    if source is None:
        return None
    if callable(source):
        route = spec.route_for(source)
        if route is not None:
            return f"{spec.prefix}{route.path}"
        action = spec.action_for(source)
        return action.name if action is not None else None
    if panel.kind is PanelKind.form:
        return source
    route = _route_by_path(spec, source)
    return f"{spec.prefix}{route.path}" if route is not None else None


def _route_by_path(spec: PluginSpec, source: str) -> Route | None:
    """The route ``source`` names, given as a path or as a mounted URL."""

    wanted = source[len(spec.prefix) :] if source.startswith(spec.prefix) else source
    return next((route for route in spec.routes if route.path == wanted), None)


def _asset_urls(spec: PluginSpec, assets_root: Path | None = None) -> list[str]:
    """Every ``.js`` under the assets directory, as URLs, sorted.

    09: the manifest lists each ``.js`` in the directory and the SPA
    injects them once as ``<script type="module">``. Sorted so the
    manifest of one directory is the same list on every restart, and
    empty — never absent — for a workflow that ships no assets.

    The files are read here rather than at ``collect`` time because a
    build that writes them under a running server should not need a
    restart to be listed; :func:`validate` has already established that
    the directory is there.
    """

    directory = spec.assets_dir(assets_root)
    if directory is None or not directory.is_dir():
        return []
    base = ASSETS_URL.format(workflow=spec.workflow)
    return sorted(
        f"{base}/{path.relative_to(directory).as_posix()}"
        for path in directory.rglob("*.js")
        if path.is_file()
    )


# -- the six checks --------------------------------------------------------


def _check_duplicates(spec: PluginSpec) -> None:
    """1. One name per declaration, within the workflow.

    Routes collide on a path *and* a method, because ``GET /words`` and
    ``POST /words`` are two operations of one resource and declaring both
    is ordinary. Actions and panels collide on their name alone: an
    action is called by name and a panel is identified by name in the
    manifest, so a second one of either is a declaration the SPA can
    never reach.
    """

    operations = [
        (route.path, method) for route in spec.routes for method in route.methods
    ]
    _refuse_duplicates(
        spec, "route", (f"{method} {path}" for path, method in operations)
    )
    _refuse_duplicates(spec, "action", (action.name for action in spec.actions))
    _refuse_duplicates(spec, "panel", (panel.name for panel in spec.panels))


def _refuse_duplicates(spec: PluginSpec, what: str, names: Iterable[str]) -> None:
    """Refuse a repeated name, listing each one that repeats."""

    seen: set[str] = set()
    repeated: list[str] = []
    for name in names:
        if name in seen and name not in repeated:
            repeated.append(name)
        seen.add(name)
    if repeated:
        raise PluginValidationError(
            f"workflow {spec.workflow!r} declares more than one {what} named "
            f"{', '.join(repr(name) for name in repeated)}"
        )


def _check_nodes(spec: PluginSpec, graph: Graph) -> None:
    """2. A declaration may only name a node the graph has.

    Both halves of it: a ``node=`` that no node answers to, and a panel
    in the ``node`` slot (or scope) that names none at all — which is a
    pane whose liveness nothing can compute, so it would never appear.
    """

    for panel in spec.panels:
        if panel.node is not None:
            if panel.node not in graph.nodes:
                raise PluginValidationError(
                    f"panel {panel.name!r} of workflow {spec.workflow!r} names "
                    f"node {panel.node!r}, which workflow {graph.name!r} does "
                    f"not have; its nodes are {sorted(graph.nodes)}"
                )
        elif Slot.node in (panel.slot, panel.scope):
            raise PluginValidationError(
                f"panel {panel.name!r} of workflow {spec.workflow!r} is "
                f"node-scoped but names no node: a node pane is shown only "
                f"while its node is live, and there is nothing to ask about"
            )


def _check_elements(spec: PluginSpec) -> None:
    """3. A ``custom`` panel renders a tag, so it must name one."""

    for panel in spec.panels:
        if panel.kind is PanelKind.custom and not panel.element:
            raise PluginValidationError(
                f"panel {panel.name!r} of workflow {spec.workflow!r} is a "
                f"custom panel with no `element`: there is no tag to render"
            )


def _check_sources(spec: PluginSpec) -> None:
    """4. A ``source`` names one of this workflow's own declarations.

    A ``form`` panel names an action — the form it renders is that
    action's model — and every other kind names a route, which is where
    its data comes from. A source pointing at a function or a name this
    workflow never declared is a pane that fetches nothing, and the only
    symptom is an empty card.
    """

    for panel in spec.panels:
        source = panel.source
        if source is None:
            continue
        if panel.kind is PanelKind.form:
            named = (
                spec.action_for(source)
                if callable(source)
                else spec.action_named(source)
            )
            if named is None:
                raise PluginValidationError(
                    f"form panel {panel.name!r} of workflow {spec.workflow!r} "
                    f"names {_source_name(source)}, which is not one of its "
                    f"actions ({sorted(action.name for action in spec.actions)})"
                )
            continue
        route = (
            spec.route_for(source) if callable(source) else _route_by_path(spec, source)
        )
        if route is None:
            raise PluginValidationError(
                f"panel {panel.name!r} of workflow {spec.workflow!r} sources "
                f"{_source_name(source)}, which is not one of its routes "
                f"({sorted(one.path for one in spec.routes)})"
            )


def _source_name(source: Callable[..., Any] | str) -> str:
    """How a ``source`` reads in a refusal."""

    return repr(getattr(source, "__name__", source))


def _check_assets(spec: PluginSpec, assets_root: Path | None) -> None:
    """5. A declared assets directory has to be there.

    Checked here rather than when the mount is built so that the refusal
    names the workflow and the declaration; the mount refuses too
    (``StaticFiles(check_dir=True)``), and both are registration-time.
    """

    directory = spec.assets_dir(assets_root)
    if directory is None or directory.is_dir():
        return
    raise PluginValidationError(
        f"workflow {spec.workflow!r} declares assets={spec.assets!r}, which "
        f"resolves to {directory} — not a directory"
    )


def _check_handlers(spec: PluginSpec) -> None:
    """6. An ``on`` names an event that exists, in a namespace it owns.

    :func:`athanore.events.names.is_known` is the vocabulary of 03 plus
    the shape of a plugin name; the workflow segment is checked here
    because only the registry knows whose declaration this is. It is the
    same rule :class:`athanore.engine.services.EventPort` enforces on the
    publishing side (18 §Plugins), from the other end.
    """

    for handler in spec.handlers:
        if not is_known(handler.event):
            raise PluginValidationError(
                f"workflow {spec.workflow!r} subscribes to {handler.event!r}, "
                f"which is not an event of the vocabulary; plugin events are "
                f"{PLUGIN_PREFIX}{spec.workflow}.<name>"
            )
        if not handler.event.startswith(PLUGIN_PREFIX):
            continue
        namespace = handler.event.split(".")[1]
        if namespace != spec.workflow:
            raise PluginValidationError(
                f"workflow {spec.workflow!r} subscribes to {handler.event!r}, "
                f"which is workflow {namespace!r}'s namespace; a plugin "
                f"subscribes in its own"
            )

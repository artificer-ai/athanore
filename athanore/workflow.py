"""The user-facing ``Workflow`` object (D48, 04 §Programmatic host).

``Workflow`` is what an author constructs, decorates node bodies onto,
and hands to a :class:`~athanore.server.Server`. It owns a
:class:`~athanore.graph.GraphBuilder` and, from T049, the plugin
declarations of 09 — which is the whole reason it is a module of its own
rather than a method on the builder: ``graph`` imports nothing from
``athanore`` (02 §Layering), so the object that composes the pure graph
with plugin declarations has to sit above both. This module is the one
place allowed to import ``athanore.graph`` and ``athanore.plugins.decl``
together.

Composition, not inheritance: the builder stays a pure object that
:mod:`athanore.graph.validate` can finalize on its own, and the two
concerns ``Workflow`` joins remain separable.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, TypeVar, get_type_hints

from pydantic import BaseModel

from athanore.graph import Graph, GraphBuilder, GraphError, finalize
from athanore.plugins.decl import (
    Action,
    Declarations,
    Handler,
    Panel,
    PanelKind,
    Route,
    Scope,
    Slot,
    coerce_methods,
    coerce_placement,
)

F = TypeVar("F", bound=Callable[..., Any])

__all__ = ["Workflow"]


class Workflow:
    """One workflow: a name, its nodes, and the graph they finalize into.

    ``finalize()`` is idempotent and caches, so the engine, the API and
    the SPA all read the *same* :class:`~athanore.graph.model.Graph`
    object rather than three equal ones built at three moments.
    """

    def __init__(self, name: str, *, assets: str | Path | None = None) -> None:
        self._builder = GraphBuilder(name)
        self._graph: Graph | None = None
        self._declarations = Declarations()
        self._assets = assets
        self._base = _caller_directory()

    @property
    def name(self) -> str:
        """The workflow's name, as it appears in URLs, events and the CLI."""
        return self._builder.name

    # -- plugin declarations (09) ------------------------------------------

    @property
    def declarations(self) -> Declarations:
        """The plugin declarations made on this workflow, in order.

        The object itself rather than a copy, because
        :func:`athanore.plugins.registry.collect` is the one reader and
        it freezes what it takes into a
        :class:`~athanore.plugins.registry.PluginSpec`.
        """
        return self._declarations

    @property
    def assets(self) -> str | Path | None:
        """The ``assets=`` directory, exactly as it was declared.

        Unresolved on purpose: a relative path means "beside the module
        that declared it", and which directory that is depends on where
        the workflow was *defined*, not on where the server was started
        (09 §Escape hatch). :attr:`assets_base` is that directory, and
        the registry is what joins the two.
        """
        return self._assets

    @property
    def assets_base(self) -> Path:
        """The directory a relative :attr:`assets` resolves against.

        The directory of the module that constructed this workflow, and
        the process's working directory when there is no such module (a
        REPL, an ``exec``). Captured at construction because that is the
        only moment the defining module is on the stack.
        """
        return self._base

    def route(
        self, path: str, *, methods: str | Sequence[str] | None = None
    ) -> Callable[[F], F]:
        """Mount the decorated function at ``/api/plugins/{workflow}{path}``.

        ``methods`` defaults to ``GET`` (09 §Declarations). The handler
        takes ``ctx: PluginContext`` — resolved from the ``run_id`` /
        ``task_id`` / ``node`` query parameters — and any other parameter
        it declares is an ordinary FastAPI one.
        """
        self._refuse_when_finalized("routes")
        methods_ = coerce_methods(methods)

        def decorate(fn: F) -> F:
            self._declarations.routes.append(Route(path, methods_, fn))
            return fn

        return decorate

    def action(
        self,
        name: str,
        *,
        title: str | None = None,
        scope: Scope | str = Slot.run,
        confirm: bool = False,
        model: type[BaseModel] | None = None,
    ) -> Callable[[F], F]:
        """Register the decorated function as the named action.

        The input model is the handler's own ``input`` annotation unless
        ``model=`` names one, because the type the author already wrote
        *is* the form the SPA renders (09 §Declarations). An action
        whose handler takes no ``input`` takes no input at all.

        ``title`` defaults to ``name``: an action the author did not
        bother to title is shown by the name they did give it, not by a
        blank button.
        """
        self._refuse_when_finalized("actions")
        scope_ = Scope(scope)

        def decorate(fn: F) -> F:
            self._declarations.actions.append(
                Action(
                    name=name,
                    title=title if title is not None else name,
                    scope=scope_,
                    confirm=confirm,
                    model=model if model is not None else _input_model(fn),
                    fn=fn,
                )
            )
            return fn

        return decorate

    def panel(
        self,
        name: str,
        *,
        slot: Slot | str,
        kind: PanelKind | str,
        placement: str = "pane",
        scope: Scope | str | None = None,
        node: str | None = None,
        source: Callable[..., Any] | str | None = None,
        element: str | None = None,
        refresh_on: Sequence[str] = (),
    ) -> Panel:
        """Declare a panel, and return it.

        A plain call rather than a decorator (D50): a panel declares data
        and has no function to wrap. The :class:`~athanore.plugins.decl.Panel`
        comes back so an author can keep it — to name it from a test, or
        to read the scope it defaulted to.

        ``scope`` defaults to ``slot``: a pane in the run's cycle is
        answered with a run, and repeating the word is how the two drift
        apart.
        """
        self._refuse_when_finalized("panels")
        slot_ = Slot(slot)
        declared = Panel(
            name=name,
            slot=slot_,
            placement=coerce_placement(placement),
            kind=PanelKind(kind),
            scope=Scope(scope) if scope is not None else slot_,
            node=node,
            source=source,
            element=element,
            refresh_on=tuple(refresh_on),
        )
        self._declarations.panels.append(declared)
        return declared

    def on(self, event: str) -> Callable[[F], F]:
        """Call the decorated function when ``event`` is committed.

        The name must be one of the vocabulary of 03, or one of this
        workflow's own ``plugin.<workflow>.<name>`` events; the registry
        refuses anything else at registration
        (:func:`athanore.plugins.registry.validate`).

        Handlers run after the transaction that emitted the event has
        committed, and one that raises is logged and dropped — a plugin
        cannot fail the engine (09 §Wire contract).
        """
        self._refuse_when_finalized("handlers")

        def decorate(fn: F) -> F:
            self._declarations.handlers.append(Handler(event, fn))
            return fn

        return decorate

    def _refuse_when_finalized(self, what: str) -> None:
        """Refuse a declaration made after the graph was frozen.

        The same rule :meth:`node` states, for the same reason: the
        registry collects and validates the declarations against the
        finalized graph at registration, so one added afterwards is one
        no manifest, no router and no subscriber will ever see.
        """
        if self._graph is not None:
            raise GraphError(
                f"workflow {self.name!r} is already finalized; "
                f"{what} cannot be declared afterwards"
            )

    def node(
        self,
        *,
        start: bool = False,
        join: bool = False,
        priority: int | None = None,
        retries: int | None = None,
        timeout: float | None = None,
        label: str | None = None,
        description: str | None = None,
    ) -> Callable[[F], F]:
        """Register the decorated function as a node of this workflow.

        Delegates to :meth:`athanore.graph.GraphBuilder.node`, whose
        docstring documents the options (04 §Node options). Refused once
        the workflow is finalized: the cached graph is handed out, so a
        node added after it would be a node no reader of ``graph`` ever
        sees.
        """
        if self._graph is not None:
            raise GraphError(
                f"workflow {self.name!r} is already finalized; "
                f"nodes cannot be added afterwards"
            )
        return self._builder.node(
            start=start,
            join=join,
            priority=priority,
            retries=retries,
            timeout=timeout,
            label=label,
            description=description,
        )

    def finalize(self) -> Graph:
        """Validate and freeze the workflow, returning its graph.

        Idempotent: the second call returns the object the first built,
        and does not re-run validation. Raises ``GraphError`` on an
        invalid graph (04 §Finalization).
        """
        if self._graph is None:
            self._graph = finalize(self._builder)
        return self._graph

    @property
    def graph(self) -> Graph:
        """The finalized graph. Raises ``GraphError`` before ``finalize()``.

        A property rather than a lazy ``finalize()`` on first read: the
        moment a workflow is frozen is a registration-time decision the
        server makes, and reading it earlier is a bug worth hearing about.
        """
        if self._graph is None:
            raise GraphError(
                f"workflow {self.name!r} is not finalized; call finalize() first"
            )
        return self._graph

    def run(self, **settings: Any) -> None:
        """Serve this one workflow: the shorthand of 04 §Programmatic host.

        Equivalent to building a :class:`~athanore.server.Server` from
        ``settings``, registering this workflow on it, and calling
        ``serve()``. Blocks until the server stops.

        ``Server`` is imported here rather than at module scope on
        purpose: it pulls in the API, uvicorn and the store, none of
        which an author needs to *define* a workflow, and
        :mod:`athanore.workflow` sits below all of them.
        """
        from athanore.server import Server
        from athanore.settings import AthanoreSettings

        server = Server(AthanoreSettings(**settings) if settings else None)
        server.register(self)
        server.serve()

    def __repr__(self) -> str:
        state = "finalized" if self._graph is not None else "building"
        return f"<Workflow {self.name!r} {len(self._builder.nodes)} nodes, {state}>"


def _caller_directory() -> Path:
    """The directory of the module that called :class:`Workflow`.

    ``assets="./static"`` is resolved relative to the declaring module
    (09 §Escape hatch), and the frame above this one is the only place
    that module's file can be read from. A caller with no file — the
    REPL, an ``exec``, a frozen entry point — resolves against the
    working directory instead, which is the best answer available and
    still one a missing directory reports honestly at registration.
    """

    frame = inspect.currentframe()
    # This function's frame, then `Workflow.__init__`'s, then the caller's.
    caller = frame.f_back.f_back if frame is not None and frame.f_back else None
    file = caller.f_globals.get("__file__") if caller is not None else None
    return Path(file).resolve().parent if file else Path.cwd()


def _input_model(fn: Callable[..., Any]) -> type[BaseModel] | None:
    """The pydantic model of ``fn``'s ``input`` parameter, or ``None``.

    "The model **is** the form" (09 §Declarations), so the annotation an
    author already wrote on ``async def override(ctx, input: Override)``
    is the declaration and there is nothing to repeat in the decorator.

    Resolved with :func:`typing.get_type_hints` because a module with
    ``from __future__ import annotations`` — which every module in this
    package has — carries its annotations as strings. A hint that cannot
    be resolved at all falls back to the raw annotation rather than
    raising: an action whose *other* parameters name a type this process
    cannot import is still an action, and it is the ``input`` one that
    has to be a model.
    """

    parameter = inspect.signature(fn).parameters.get("input")
    if parameter is None:
        return None
    try:
        annotation = get_type_hints(fn).get("input", parameter.annotation)
    except Exception:
        annotation = parameter.annotation
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    raise TypeError(
        f"the `input` parameter of action handler {fn.__name__!r} must be "
        f"annotated with a pydantic model — it is the form the SPA renders "
        f"(09 §Declarations) — but it is annotated {annotation!r}"
    )

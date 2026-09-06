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

from collections.abc import Callable
from typing import Any, TypeVar

from athanore.graph import Graph, GraphBuilder, GraphError, finalize

F = TypeVar("F", bound=Callable[..., Any])

__all__ = ["Workflow"]


class Workflow:
    """One workflow: a name, its nodes, and the graph they finalize into.

    ``finalize()`` is idempotent and caches, so the engine, the API and
    the SPA all read the *same* :class:`~athanore.graph.model.Graph`
    object rather than three equal ones built at three moments.
    """

    def __init__(self, name: str) -> None:
        self._builder = GraphBuilder(name)
        self._graph: Graph | None = None

    @property
    def name(self) -> str:
        """The workflow's name, as it appears in URLs, events and the CLI."""
        return self._builder.name

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
        # `athanore.server` is T051's module; the ignore comes off with it.
        from athanore.server import Server  # pyright: ignore[reportMissingImports]
        from athanore.settings import AthanoreSettings

        server = Server(AthanoreSettings(**settings) if settings else None)
        server.register(self)
        server.serve()

    def __repr__(self) -> str:
        state = "finalized" if self._graph is not None else "building"
        return f"<Workflow {self.name!r} {len(self._builder.nodes)} nodes, {state}>"

"""Graph DSL: the signature is the graph, the return value is the routing.

The three rules, unchanged from the MVP: the signature is the graph, the
return value is the routing, and the exception is the failure policy.
This module is pure — no I/O, no asyncio — and imports nothing from the
rest of ``athanore``.

``GraphBuilder`` collects nodes and freezes them into a
:class:`~athanore.graph.model.Graph`; the checks that make a graph
*valid* live in :mod:`athanore.graph.validate`.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from athanore.graph.model import Graph, Node

F = TypeVar("F", bound=Callable[..., Any])


class GraphError(Exception):
    """Raised for invalid workflow graphs, at finalization or routing time."""


@dataclass(frozen=True)
class Transition:
    """A serializable routing decision: go to `target` carrying `payload`."""

    target: str
    payload: Any = None


class EdgeRef:
    """Injected stand-in for a successor node. Calling it routes to it."""

    __slots__ = ("name",)

    def __init__(self, name: str) -> None:
        self.name = name

    def __call__(self, payload: Any = None) -> Transition:
        return Transition(self.name, payload)

    def __repr__(self) -> str:
        return f"<edge {self.name}>"


def parse_signature(fn: Callable[..., Any]) -> tuple[list[str], str | None]:
    """Two forms:

    - With ``/``: parameters before it are edges, the first after is payload.
    - Without ``/``: positional params are edges; the payload (rare — state
      flows through comments) is a keyword-only param after ``*``, e.g.
      ``async def architecture(engineering, *, deliverable)``.
    """
    sig = inspect.signature(fn)
    params = list(sig.parameters.values())
    has_positional_only = any(
        p.kind is inspect.Parameter.POSITIONAL_ONLY for p in params
    )
    edges: list[str] = []
    payload_param: str | None = None
    for param in params:
        if param.kind is inspect.Parameter.POSITIONAL_ONLY:
            edges.append(param.name)
        elif param.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD:
            if has_positional_only:
                if payload_param is None:
                    payload_param = param.name
            else:
                edges.append(param.name)
        elif param.kind is inspect.Parameter.KEYWORD_ONLY:
            if payload_param is None:
                payload_param = param.name
        else:
            raise GraphError(f"node {fn.__name__!r}: *args/**kwargs are not supported")
    return edges, payload_param


class GraphBuilder:
    """Collects the nodes of one workflow and freezes them into a graph.

    The decorator returns the function unchanged, so a node body stays
    directly callable and directly testable.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self.nodes: dict[str, Node] = {}

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
        """Register the decorated function as a node.

        The node name is ``fn.__name__``; its edges and payload slot are
        parsed from the function signature. The options are the metadata
        seam of 04 §Node options: ``start`` (exactly one per workflow),
        ``join`` (this node closes a fan-out and needs a payload slot),
        ``priority``, ``retries`` and ``timeout`` (``None`` meaning the
        server default), and ``label``/``description`` for the UI graph,
        which fall back to the function's name and docstring.
        """

        def decorator(fn: F) -> F:
            name = fn.__name__
            if name in self.nodes:
                raise GraphError(f"duplicate node name: {name!r}")
            edges, payload_param = parse_signature(fn)
            self.nodes[name] = Node(
                name=name,
                fn=fn,
                edges=tuple(edges),
                payload_param=payload_param,
                start=start,
                join=join,
                priority=priority,
                retries=retries,
                timeout=timeout,
                label=label or fn.__name__,
                description=description or inspect.getdoc(fn),
            )
            return fn

        return decorator

    def build(self) -> Graph:
        """Freeze the collected nodes into a :class:`Graph`.

        Only the one check a graph object cannot be built without: a
        graph has to know where it starts. The rest of finalization is
        :func:`athanore.graph.validate.finalize`, which calls this.
        """
        starts = [node.name for node in self.nodes.values() if node.start]
        if len(starts) != 1:
            raise GraphError(
                f"workflow {self.name!r} needs exactly one start node, "
                f"found {len(starts)}"
            )
        return Graph(name=self.name, nodes=dict(self.nodes), start=starts[0])

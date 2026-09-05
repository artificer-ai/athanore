"""Graph DSL: the signature is the graph, the return value is the routing.

The three rules, unchanged from the MVP: the signature is the graph, the
return value is the routing, and the exception is the failure policy.
This module is pure — no I/O, no asyncio — and imports nothing from the
rest of ``athanore``.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


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


@dataclass
class Node:
    """A single node of a workflow graph."""

    name: str
    fn: Callable[..., Any]
    edges: list[str]
    payload_param: str | None
    start: bool = False
    priority: int | None = None
    generation: int = 0


def _parse_signature(fn: Callable[..., Any]) -> tuple[list[str], str | None]:
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


class AthanoreWorkflow:
    """A code-defined graph of nodes."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.nodes: dict[str, Node] = {}
        self._finalized = False

    def node(
        self, *, start: bool = False, priority: int | None = None
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Register the decorated function as a node.

        The node name is ``fn.__name__``; its edges and payload slot are
        parsed from the function signature. The function is returned
        unchanged, so it stays directly callable.
        """

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            name = fn.__name__
            if name in self.nodes:
                raise GraphError(f"duplicate node name: {name!r}")
            edges, payload_param = _parse_signature(fn)
            self.nodes[name] = Node(
                name=name,
                fn=fn,
                edges=edges,
                payload_param=payload_param,
                start=start,
                priority=priority,
            )
            return fn

        return decorator

    def finalize(self) -> None:
        """Resolve edges, compute generations, fail fast on bad graphs.

        Idempotent: a second call is a no-op. Raises ``GraphError`` when
        there is not exactly one start node, when an edge names a node
        that does not exist, or when any node is unreachable from the
        start.
        """
        if self._finalized:
            return
        starts = [n for n in self.nodes.values() if n.start]
        if len(starts) != 1:
            raise GraphError(
                f"workflow {self.name!r} needs exactly one start node, "
                f"found {len(starts)}"
            )
        for node in self.nodes.values():
            for edge in node.edges:
                if edge not in self.nodes:
                    raise GraphError(
                        f"node {node.name!r} declares edge {edge!r}, "
                        f"but no such node exists"
                    )
        # generations: first-reach depth from the start node (BFS)
        start = starts[0]
        gens: dict[str, int] = {start.name: 0}
        queue = [start.name]
        for name in queue:  # queue grows as we append
            for edge in self.nodes[name].edges:
                if edge not in gens:
                    gens[edge] = gens[name] + 1
                    queue.append(edge)
        unreachable = sorted(set(self.nodes) - set(gens))
        if unreachable:
            raise GraphError(
                f"workflow {self.name!r}: unreachable nodes: {unreachable}"
            )
        for name, gen in gens.items():
            self.nodes[name].generation = gen
        self._finalized = True

    def start_node(self) -> Node:
        return next(n for n in self.nodes.values() if n.start)

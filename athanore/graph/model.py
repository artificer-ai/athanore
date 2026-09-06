"""The frozen graph model: a workflow's shape once it is built.

``Node`` and ``Graph`` are what the builder produces and validation
returns. They are immutable: generations are computed *into* the built
graph rather than mutated onto it afterwards, so a finalized graph
handed to the engine, the API or the SPA cannot drift.

Pure — no I/O, no asyncio, and nothing imported from the rest of
``athanore``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True)
class Node:
    """A single node of a workflow graph.

    ``edges`` and ``payload_param`` come from the body's signature (the
    first rule: the signature is the graph). Everything from ``start``
    down is node metadata — the seam new capability attaches to.

    ``priority`` and ``retries`` of ``None`` mean "the server default";
    ``timeout`` of ``None`` means no wall-clock cap on one attempt.
    ``generation`` is the BFS depth from the start node, filled in by
    :func:`athanore.graph.validate.finalize`.
    """

    name: str
    fn: Callable[..., Any]
    edges: tuple[str, ...]
    payload_param: str | None
    start: bool = False
    join: bool = False
    priority: int | None = None
    retries: int | None = None
    timeout: float | None = None
    label: str = ""
    description: str | None = None
    generation: int = 0


@dataclass(frozen=True)
class Graph:
    """A built workflow graph: its name, its nodes, and where it starts.

    ``nodes`` is wrapped in a read-only view on construction, so the
    whole object is frozen and not merely annotated as such.
    """

    name: str
    nodes: Mapping[str, Node]
    start: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "nodes", MappingProxyType(dict(self.nodes)))

    @property
    def start_node(self) -> Node:
        """The node execution begins at."""
        return self.nodes[self.start]

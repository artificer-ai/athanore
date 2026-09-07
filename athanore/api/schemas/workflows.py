"""What a workflow looks like on the wire (08 §Workflows).

Two views of the same registration. :class:`WorkflowOut` is the shape —
its nodes, their options, and the pool it runs on — and is what the New
Run overlay and the workflow library list read. :class:`SourceOut` is the
Python behind it: the module text and the line each node's body starts
on, which is what the library's source viewer highlights (10 §Overlays,
D35).

Both are built from a finalized :class:`~athanore.graph.model.Graph`
rather than from the :class:`~athanore.workflow.Workflow` object, because
the graph is what the engine registered and therefore what the server can
actually run.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from athanore.graph import Graph, Node

__all__ = [
    "NodeOut",
    "SourceNode",
    "SourceOut",
    "WorkflowOut",
    "WorkflowPlugin",
]


class NodeOut(BaseModel):
    """One node's edges and its options, as 08 §Workflows lists them.

    ``priority`` and ``retries`` of ``null`` mean "the server default"
    and ``timeout`` of ``null`` means no wall-clock cap on one attempt —
    the node metadata of 04 §Node options, unresolved, because what the
    default *is* belongs to the settings of the server running it.
    """

    edges: list[str] = Field(
        description="The nodes this one may transition to, in declaration order."
    )
    generation: int = Field(
        description="BFS depth from the start node; a loop-back edge targets a "
        "generation at or below its source."
    )
    priority: int | None = Field(
        default=None, description="Dispatch priority, or null for the server default."
    )
    retries: int | None = Field(
        default=None, description="Retry budget, or null for the server default."
    )
    timeout: float | None = Field(
        default=None, description="Seconds one attempt may run, or null for no cap."
    )
    label: str = Field(description="The display name; the function's name by default.")
    description: str | None = Field(
        default=None, description="The body's docstring, unless the node overrode it."
    )

    @classmethod
    def of(cls, node: Node) -> NodeOut:
        """The wire view of one finalized node."""

        return cls(
            edges=list(node.edges),
            generation=node.generation,
            priority=node.priority,
            retries=node.retries,
            timeout=node.timeout,
            label=node.label,
            description=node.description,
        )


class WorkflowPlugin(BaseModel):
    """The panels and actions a workflow contributes (09 §Wire contract).

    Both lists are empty until the plugin registry lands: the field is
    part of the contract now so the SPA can read a workflow's plugin
    surface from the workflow itself, and the entries it will carry are
    the manifest's own (09).
    """

    panels: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Panel declarations, as `/api/plugins` lists them.",
    )
    actions: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Action declarations, as `/api/plugins` lists them.",
    )


class WorkflowOut(BaseModel):
    """One registered workflow: its graph, its capacity, its plugins."""

    name: str = Field(description="The workflow's name, as it appears in URLs.")
    start: str = Field(description="The node a new run begins at.")
    pool: str = Field(description="The pool this workflow's tasks are dispatched on.")
    capacity: int = Field(description="Slots that pool has, in total.")
    in_flight: int = Field(
        description="Slots of that pool leased right now, across every workflow "
        "bound to it."
    )
    nodes: dict[str, NodeOut] = Field(
        description="Every node of the finalized graph, by name."
    )
    plugin: WorkflowPlugin = Field(
        description="What this workflow contributes to the UI (09)."
    )

    @classmethod
    def of(
        cls,
        graph: Graph,
        *,
        pool: str,
        capacity: int,
        in_flight: int,
        plugin: WorkflowPlugin | None = None,
    ) -> WorkflowOut:
        """The wire view of ``graph`` running on the named pool."""

        return cls(
            name=graph.name,
            start=graph.start,
            pool=pool,
            capacity=capacity,
            in_flight=in_flight,
            nodes={name: NodeOut.of(node) for name, node in graph.nodes.items()},
            plugin=plugin if plugin is not None else WorkflowPlugin(),
        )


class SourceNode(BaseModel):
    """Where one node's body starts in the returned source."""

    line: int = Field(
        description="The 1-based line of the body's first decorator or `def`."
    )


class SourceOut(BaseModel):
    """A workflow's module source, and the line each node begins on.

    ``nodes`` names the nodes whose bodies are defined **in this file**.
    A workflow may register a function imported from somewhere else; that
    node has no line in this source, and it is left out rather than given
    a number that points at the wrong text (01 §Real data only).
    """

    file: str = Field(description="The absolute path of the module the source is from.")
    source: str = Field(description="That module's text, in full.")
    nodes: dict[str, SourceNode] = Field(
        description="The line each node's body starts on, for the nodes defined here."
    )

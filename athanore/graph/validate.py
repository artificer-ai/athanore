"""Finalization: the checks that turn a builder into a valid graph.

``finalize`` is the whole of 04 §Finalization. It fails fast — a bad
graph is a code defect, and the cheapest place to find one is before the
first task is ever enqueued — and returns the frozen graph with
generations filled in.
"""

from __future__ import annotations

import re
from dataclasses import replace

from athanore.graph.builder import GraphBuilder, GraphError
from athanore.graph.model import Graph, Node

#: A workflow name is a lowercase identifier: it appears in URLs, event
#: payloads and CLI verbs, so the shape is fixed rather than merely
#: "an identifier". Matched with ``fullmatch``: ``$`` alone would also
#: accept a trailing newline.
NAME_RE = re.compile(r"[a-z][a-z0-9_]*")


def finalize(builder: GraphBuilder) -> Graph:
    """Validate ``builder`` and return its frozen, generation-filled graph.

    Raises ``GraphError`` when the workflow name is not a lowercase
    identifier, when there is not exactly one start node, when an edge
    names a node that does not exist, when a ``join=True`` node has no
    payload slot to receive its branches, or when any node is
    unreachable from the start. Duplicate node names are the sixth of
    04's list and are rejected earlier, by ``GraphBuilder.node``, which
    is the only place a second node of a name can arrive.
    """
    if not NAME_RE.fullmatch(builder.name):
        raise GraphError(
            f"workflow name {builder.name!r} must match {NAME_RE.pattern!r}"
        )
    graph = builder.build()
    _check_edges(graph)
    _check_joins(graph)
    generations = _generations(graph)
    unreachable = sorted(set(graph.nodes) - set(generations))
    if unreachable:
        raise GraphError(f"workflow {graph.name!r}: unreachable nodes: {unreachable}")
    return replace(
        graph,
        nodes={
            name: replace(node, generation=generations[name])
            for name, node in graph.nodes.items()
        },
    )


def _check_edges(graph: Graph) -> None:
    for node in graph.nodes.values():
        for edge in node.edges:
            if edge not in graph.nodes:
                raise GraphError(
                    f"node {node.name!r} declares edge {edge!r}, "
                    f"but no such node exists"
                )


def _check_joins(graph: Graph) -> None:
    for node in graph.nodes.values():
        if node.join and node.payload_param is None:
            raise GraphError(
                f"node {node.name!r} is a join and must declare a payload "
                f"slot to receive its branches"
            )


def _generations(graph: Graph) -> dict[str, int]:
    """BFS depth from the start node: first reach, so cycles do not loop."""
    generations = {graph.start: 0}
    queue = [graph.start]
    for name in queue:  # the queue grows as we append
        node: Node = graph.nodes[name]
        for edge in node.edges:
            if edge not in generations:
                generations[edge] = generations[name] + 1
                queue.append(edge)
    return generations

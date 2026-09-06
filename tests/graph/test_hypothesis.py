"""Property tests for graph finalization.

Three properties, over random graphs that include cycles — a cycle is
legal (the driver's own seat has three), so a generator that only made
DAGs would prove much less than it looks:

- ``finalize`` never raises on a valid graph;
- every generation equals the shortest-path depth from the start node;
- every unreachable node is named in the error.
"""

from collections import deque
from collections.abc import Mapping, Sequence
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from athanore.graph import GraphBuilder, GraphError, finalize

MAX_NODES = 8


def node_body(name: str, edges: Sequence[str], *, payload: bool = False) -> Any:
    """Build a node body whose signature declares ``edges``.

    The DSL reads the signature, so a generated graph has to be
    generated as real function signatures rather than as data.
    """
    if edges:
        params = ", ".join(edges) + ", /" + (", payload" if payload else "")
    else:
        params = "*, payload" if payload else ""
    namespace: dict[str, Any] = {}
    exec(f"async def {name}({params}): ...", namespace)
    return namespace[name]


def build(name: str, edges: Mapping[str, Sequence[str]], start: str) -> GraphBuilder:
    wf = GraphBuilder(name)
    for node, successors in edges.items():
        wf.node(start=node == start)(node_body(node, successors))
    return wf


def shortest_depths(edges: Mapping[str, Sequence[str]], start: str) -> dict[str, int]:
    """Plain BFS, written independently of the implementation."""
    depths = {start: 0}
    queue = deque([start])
    while queue:
        name = queue.popleft()
        for successor in edges[name]:
            if successor not in depths:
                depths[successor] = depths[name] + 1
                queue.append(successor)
    return depths


@st.composite
def connected_graphs(draw: st.DrawFn) -> dict[str, list[str]]:
    """A random reachable graph over ``n0…nk``, rooted at ``n0``.

    Every node past the first takes a parent drawn from the nodes before
    it, which is what makes it reachable; the extra edges are drawn from
    the full square, so back edges and self-loops — cycles — are the
    common case rather than the exception.
    """
    count = draw(st.integers(min_value=1, max_value=MAX_NODES))
    names = [f"n{i}" for i in range(count)]
    edges: dict[str, set[str]] = {name: set() for name in names}
    for index in range(1, count):
        parent = draw(st.integers(min_value=0, max_value=index - 1))
        edges[names[parent]].add(names[index])
    extra = draw(
        st.lists(
            st.tuples(
                st.integers(min_value=0, max_value=count - 1),
                st.integers(min_value=0, max_value=count - 1),
            ),
            max_size=2 * MAX_NODES,
        )
    )
    for source, target in extra:
        edges[names[source]].add(names[target])
    return {name: sorted(successors) for name, successors in edges.items()}


@st.composite
def graphs_with_islands(draw: st.DrawFn) -> tuple[dict[str, list[str]], list[str]]:
    """A reachable graph plus islands nothing reachable points at.

    The islands may point back into the reachable part — an out-edge is
    not what makes a node reachable — and at each other.
    """
    edges = {
        name: list(successors) for name, successors in draw(connected_graphs()).items()
    }
    reachable = list(edges)
    island_count = draw(st.integers(min_value=1, max_value=4))
    islands = [f"island{i}" for i in range(island_count)]
    targets = reachable + islands
    for island in islands:
        edges[island] = draw(
            st.lists(st.sampled_from(targets), max_size=3, unique=True)
        )
    return edges, islands


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(connected_graphs())
def test_finalize_accepts_every_valid_graph(edges: dict[str, list[str]]):
    finalize(build("t", edges, "n0"))


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(connected_graphs())
def test_generations_are_shortest_path_depths(edges: dict[str, list[str]]):
    graph = finalize(build("t", edges, "n0"))
    expected = shortest_depths(edges, "n0")
    assert {name: node.generation for name, node in graph.nodes.items()} == expected


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(graphs_with_islands())
def test_every_unreachable_node_is_reported(
    case: tuple[dict[str, list[str]], list[str]],
):
    edges, islands = case
    with pytest.raises(GraphError, match="unreachable") as excinfo:
        finalize(build("t", edges, "n0"))
    message = str(excinfo.value)
    for island in islands:
        assert repr(island) in message
    for reachable in set(edges) - set(islands):
        assert repr(reachable) not in message

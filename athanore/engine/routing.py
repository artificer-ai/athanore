"""Rule 2: the return value is the routing (04 §Routing interpretation).

:func:`interpret` is the whole of the 04 table, and it is pure: a node,
a value the body returned, and out come the transitions the runner
enqueues. It reads the graph and it raises ``GraphError``; it touches no
store, no event bus and no clock, which is what lets every row of the
table be a two-line test.

The table, row for row:

============================================  ==============================
Return value                                  Result
============================================  ==============================
``Transition``                                that transition
``EdgeRef``                                   ``Transition(ref.name)``
non-empty list/tuple of refs/transitions      fan-out, one branch each
``[]`` / ``()``                               terminal, branch value ``[]``
anything else, node has 0 edges               terminal
anything else, node has 1 edge                that edge, carrying the value
anything else, node has ≥2 edges              ``GraphError`` (ambiguous)
============================================  ==============================

A transition targeting an edge the node did not declare is a
``GraphError`` whichever row produced it. Payloads are coerced with
:func:`~athanore.graph.jsonable`, so what the runner persists and what
the target node receives are the same value.
"""

from __future__ import annotations

from typing import Any, cast

from athanore.graph import EdgeRef, GraphError, Node, Transition, jsonable


def interpret(node: Node, value: Any) -> list[Transition]:
    """Turn ``node``'s return ``value`` into the transitions to enqueue.

    An empty list is the terminal answer, not the fan-out of one edge:
    a stage may legitimately decide there is nothing to split, and an
    empty fan-out ends its branch with the value ``[]`` (04 §Routing
    edge cases).

    Raises ``GraphError`` when a plain value is returned by a node with
    two or more successors — the engine will not guess which one — and
    when any transition names a node that is not among ``node.edges``.
    """
    transitions = _explicit(value)
    if transitions is None:
        transitions = _implicit(node, value)
    for transition in transitions:
        if transition.target not in node.edges:
            raise GraphError(
                f"node {node.name!r} routed to undeclared edge "
                f"{transition.target!r}; its edges are {list(node.edges)}"
            )
    return transitions


def _explicit(value: Any) -> list[Transition] | None:
    """The routing the body asked for, or ``None`` if it asked for none.

    A list is a fan-out only when every element is a ref or a
    transition; a list with anything else in it is a plain value like
    any other, and takes the node's single edge or fails on its several.
    """
    if isinstance(value, Transition):
        return [_coerce(value)]
    if isinstance(value, EdgeRef):
        return [Transition(value.name)]
    if isinstance(value, (list, tuple)):
        items = cast("list[Any] | tuple[Any, ...]", value)
        if not items:
            return []
        fan_out: list[Transition] = []
        for item in items:
            if isinstance(item, Transition):
                fan_out.append(_coerce(item))
            elif isinstance(item, EdgeRef):
                fan_out.append(Transition(item.name))
            else:
                return None
        return fan_out
    return None


def _implicit(node: Node, value: Any) -> list[Transition]:
    """The routing a plain return value implies, from the node's shape."""
    if not node.edges:
        return []
    if len(node.edges) == 1:
        return [Transition(node.edges[0], jsonable(value))]
    raise GraphError(
        f"node {node.name!r} has {len(node.edges)} successors "
        f"{list(node.edges)}; return an edge ref (e.g. "
        f"`return {node.edges[0]}(value)`) to choose one"
    )


def _coerce(transition: Transition) -> Transition:
    """The same transition with a JSON-serializable payload."""
    return Transition(transition.target, jsonable(transition.payload))

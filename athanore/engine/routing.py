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


def is_fan_out(value: Any) -> bool:
    """Whether ``value`` is the *list* form of a routing decision.

    :func:`interpret` erases the difference: ``return ref`` and
    ``return [ref]`` both come back as one transition. The engine still
    needs it, because a fan-out pushes a branch frame onto every child
    and a single transition copies the parent's stack unchanged (04
    §Branch frames) — including a fan-out of one, so that a stage which
    "usually" splits still closes its join when it produces one branch
    (04 §Fan-in). Naming it here keeps the runner from re-deriving what
    counts as a fan-out and drifting from the table above.

    ``[]`` is not a fan-out: it is the terminal answer (04 §Routing edge
    cases), and neither is a list with anything but refs and transitions
    in it, which is a plain value.
    """
    if not isinstance(value, (list, tuple)):
        return False
    items = cast("list[Any] | tuple[Any, ...]", value)
    return bool(items) and all(
        isinstance(item, (EdgeRef, Transition)) for item in items
    )


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
        if not is_fan_out(items):
            return None
        return [
            _coerce(item) if isinstance(item, Transition) else Transition(item.name)
            for item in cast("list[EdgeRef | Transition]", items)
        ]
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

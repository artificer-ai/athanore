"""Rule 2 and rule 3: routing interpretation and failure classes (T021).

One test per row of the 04 §Routing interpretation table, then its
§Routing edge cases, then the §Failure classes predicate. Everything
here is pure: `interpret` takes a finalized node and a value, and the
runner that will call it is T024.
"""

from dataclasses import dataclass

import pytest
from pydantic import BaseModel

from athanore.engine.errors import NON_RETRYABLE, NonRetryable, is_retryable
from athanore.engine.routing import interpret
from athanore.graph import (
    EdgeRef,
    Graph,
    GraphBuilder,
    GraphError,
    Transition,
    finalize,
)


def fork() -> Graph:
    """A start node with two successors: plain returns are ambiguous."""
    wf = GraphBuilder("fork")

    @wf.node(start=True)
    async def choose(left, right): ...

    @wf.node()
    async def left(): ...

    @wf.node()
    async def right(): ...

    return finalize(wf)


def chain() -> Graph:
    """A start node with exactly one successor: plain returns auto-route."""
    wf = GraphBuilder("chain")

    @wf.node(start=True)
    async def first(second): ...

    @wf.node()
    async def second(): ...

    return finalize(wf)


def leaf() -> Graph:
    """A one-node graph: its start node has no successors at all."""
    wf = GraphBuilder("leaf")

    @wf.node(start=True)
    async def only(): ...

    return finalize(wf)


# --- the table, row for row -------------------------------------------------


def test_transition_is_returned_as_itself():
    node = fork().nodes["choose"]
    assert interpret(node, Transition("left", 7)) == [Transition("left", 7)]


def test_edge_ref_becomes_a_transition_with_no_payload():
    node = fork().nodes["choose"]
    assert interpret(node, EdgeRef("right")) == [Transition("right", None)]


def test_called_edge_ref_carries_its_payload():
    node = fork().nodes["choose"]
    assert interpret(node, EdgeRef("left")("go")) == [Transition("left", "go")]


def test_list_of_refs_fans_out_one_branch_each():
    node = fork().nodes["choose"]
    value = [EdgeRef("left")("a"), EdgeRef("right")("b")]
    assert interpret(node, value) == [
        Transition("left", "a"),
        Transition("right", "b"),
    ]


def test_tuple_of_refs_fans_out_too():
    node = fork().nodes["choose"]
    value = (EdgeRef("left"), EdgeRef("right"))
    assert interpret(node, value) == [
        Transition("left", None),
        Transition("right", None),
    ]


def test_mixed_list_of_edge_refs_and_transitions():
    node = fork().nodes["choose"]
    value = [EdgeRef("left")(1), Transition("right", 2)]
    assert interpret(node, value) == [
        Transition("left", 1),
        Transition("right", 2),
    ]


def test_plain_value_with_no_edges_is_terminal():
    assert interpret(leaf().nodes["only"], {"done": True}) == []


def test_plain_value_with_one_edge_auto_transitions():
    node = chain().nodes["first"]
    assert interpret(node, {"spec": "x"}) == [Transition("second", {"spec": "x"})]


def test_plain_value_with_two_edges_is_ambiguous():
    node = fork().nodes["choose"]
    with pytest.raises(GraphError, match="2 successors"):
        interpret(node, "which way?")


# --- the edge cases ---------------------------------------------------------


@pytest.mark.parametrize("empty", [[], ()])
def test_empty_fan_out_is_terminal(empty: list[object] | tuple[object, ...]):
    """`return []` ends the branch; it is not the node's single edge."""
    assert interpret(chain().nodes["first"], empty) == []
    assert interpret(fork().nodes["choose"], empty) == []
    assert interpret(leaf().nodes["only"], empty) == []


def test_fan_out_of_one_is_not_a_special_case():
    node = fork().nodes["choose"]
    assert interpret(node, [EdgeRef("left")("a")]) == interpret(
        node, EdgeRef("left")("a")
    )


def test_plain_none_with_one_edge_carries_none():
    node = chain().nodes["first"]
    assert interpret(node, None) == [Transition("second", None)]


def test_a_returned_transition_wins_over_the_single_edge():
    """A body cannot carry a transition as a payload (04 §Routing edge cases)."""
    wf = GraphBuilder("both")

    @wf.node(start=True)
    async def first(second): ...

    @wf.node()
    async def second(third): ...

    @wf.node()
    async def third(): ...

    graph = finalize(wf)
    assert interpret(graph.nodes["first"], Transition("second", 1)) == [
        Transition("second", 1)
    ]


def test_list_with_a_plain_element_is_a_plain_value():
    """Only an all-refs list is a fan-out; the rest is one payload."""
    node = chain().nodes["first"]
    assert interpret(node, [EdgeRef("second"), 3]) == [
        Transition("second", ["<edge second>", 3])
    ]
    with pytest.raises(GraphError, match="2 successors"):
        interpret(fork().nodes["choose"], [EdgeRef("left"), 3])


def test_undeclared_target_is_a_graph_error():
    node = fork().nodes["choose"]
    with pytest.raises(GraphError, match="undeclared edge 'elsewhere'"):
        interpret(node, Transition("elsewhere"))


def test_undeclared_target_inside_a_fan_out_is_a_graph_error():
    node = fork().nodes["choose"]
    with pytest.raises(GraphError, match="undeclared edge 'nowhere'"):
        interpret(node, [EdgeRef("left"), EdgeRef("nowhere")])


def test_a_node_may_not_route_to_itself_unless_it_declares_the_edge():
    with pytest.raises(GraphError, match="undeclared edge 'first'"):
        interpret(chain().nodes["first"], Transition("first"))


# --- payload coercion -------------------------------------------------------


class Spec(BaseModel):
    title: str
    size: int


@dataclass
class Note:
    text: str


def test_pydantic_payload_becomes_a_dict():
    node = fork().nodes["choose"]
    value = EdgeRef("left")(Spec(title="port", size=3))
    assert interpret(node, value) == [Transition("left", {"title": "port", "size": 3})]


def test_payload_coercion_reaches_inside_containers():
    node = chain().nodes["first"]
    assert interpret(node, {"notes": [Note("a")]}) == [
        Transition("second", {"notes": [{"text": "a"}]})
    ]


def test_unserializable_payload_falls_back_to_str():
    """`jsonable`'s last resort, so a body never kills a run (04)."""

    class Opaque:
        def __repr__(self) -> str:
            return "<opaque>"

    node = chain().nodes["first"]
    assert interpret(node, Opaque()) == [Transition("second", "<opaque>")]


# --- failure classes (rule 3, 04 §Failure classes, D42) ---------------------


class Refused(NonRetryable):
    """A user-land narrowing of the policy."""


@pytest.mark.parametrize(
    "exc",
    [
        GraphError("routed nowhere"),
        NonRetryable("the agent refused"),
        Refused("still refused"),
    ],
)
def test_dead_letter_on_the_first_attempt(exc: Exception):
    assert is_retryable(exc) is False


@pytest.mark.parametrize(
    "exc",
    [
        TimeoutError("the node clock ran out"),
        RuntimeError("a flaky subprocess"),
        ValueError("bad output"),
        Exception("anything else"),
    ],
)
def test_everything_else_retries(exc: Exception):
    assert is_retryable(exc) is True


def test_asyncio_timeout_error_is_the_builtin_timeout_error():
    """3.11+ aliases them; the retryable row must cover both names."""
    import asyncio

    assert asyncio.TimeoutError is TimeoutError
    assert is_retryable(TimeoutError()) is True


def test_non_retryable_is_the_two_documented_types():
    assert NON_RETRYABLE == (GraphError, NonRetryable)

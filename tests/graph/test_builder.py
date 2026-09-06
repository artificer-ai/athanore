"""Graph DSL unit tests.

Ported from the MVP's `tests/test_graph.py` (`docs/porting-ledger.md`),
onto the split package: the builder collects, `finalize` validates and
returns a frozen graph, and generations live on that graph rather than
being mutated onto the builder's nodes.
"""

from dataclasses import FrozenInstanceError, dataclass

import pytest
from pydantic import BaseModel

from athanore.graph import (
    AthanoreWorkflow,
    EdgeRef,
    Graph,
    GraphBuilder,
    GraphError,
    Transition,
    finalize,
    jsonable,
    parse_signature,
)


def test_parse_edges_and_payload():
    wf = GraphBuilder("t")

    @wf.node(start=True)
    async def a(b, /, x): ...

    @wf.node()
    async def b(): ...

    graph = finalize(wf)
    assert graph.nodes["a"].edges == ("b",)
    assert graph.nodes["a"].payload_param == "x"
    assert graph.nodes["b"].edges == ()
    assert graph.nodes["b"].payload_param is None
    assert graph.nodes["a"].generation == 0
    assert graph.nodes["b"].generation == 1


def test_bare_edge_signatures():
    """No `/`: positionals are edges; keyword-only is the payload slot."""
    wf = GraphBuilder("t")

    @wf.node(start=True)
    async def a(b): ...

    @wf.node()
    async def b(c, d): ...

    @wf.node()
    async def c(e, *, deliverable): ...

    @wf.node()
    async def d(): ...

    @wf.node()
    async def e(): ...

    graph = finalize(wf)
    assert graph.nodes["a"].edges == ("b",)
    assert graph.nodes["a"].payload_param is None
    assert graph.nodes["b"].edges == ("c", "d")
    assert graph.nodes["c"].edges == ("e",)
    assert graph.nodes["c"].payload_param == "deliverable"
    assert graph.nodes["d"].edges == ()


def test_cycle_gets_first_reach_generation():
    wf = GraphBuilder("t")

    @wf.node(start=True)
    async def a(b, /, x): ...

    @wf.node()
    async def b(c, /, x): ...

    @wf.node()
    async def c(b, d, /, x): ...

    @wf.node()
    async def d(): ...

    graph = finalize(wf)
    assert graph.nodes["c"].generation == 2
    assert graph.nodes["b"].generation == 1  # first reach, not looped


def test_unknown_edge_fails():
    wf = GraphBuilder("t")

    @wf.node(start=True)
    async def a(nope, /, x): ...

    with pytest.raises(GraphError, match="no such node"):
        finalize(wf)


def test_duplicate_node_fails():
    wf = GraphBuilder("t")

    @wf.node(start=True)
    async def a(): ...

    with pytest.raises(GraphError, match="duplicate"):

        @wf.node()
        async def a(): ...  # noqa: F811


def test_no_start_fails():
    wf = GraphBuilder("t")

    @wf.node()
    async def a(): ...

    with pytest.raises(GraphError, match="start node"):
        finalize(wf)


def test_two_starts_fail():
    wf = GraphBuilder("t")

    @wf.node(start=True)
    async def a(b, /, x): ...

    @wf.node(start=True)
    async def b(): ...

    with pytest.raises(GraphError, match="found 2"):
        finalize(wf)


def test_unreachable_node_fails():
    wf = GraphBuilder("t")

    @wf.node(start=True)
    async def a(): ...

    @wf.node()
    async def island(): ...

    with pytest.raises(GraphError, match="unreachable"):
        finalize(wf)


def test_varargs_rejected():
    wf = GraphBuilder("t")

    with pytest.raises(GraphError, match=r"\*args"):

        @wf.node(start=True)
        async def a(*args): ...

    with pytest.raises(GraphError, match=r"\*args"):

        @wf.node(start=True)
        async def b(**kwargs): ...


def test_parse_signature_is_public():
    def body(one, two, /, payload): ...

    assert parse_signature(body) == (["one", "two"], "payload")


# --- node options (04 §Node options) ---------------------------------


def test_node_options_are_recorded():
    wf = GraphBuilder("t")

    @wf.node(start=True, priority=0, retries=1, timeout=600.0)
    async def a(b, /, x):
        """The docstring is the description."""

    @wf.node(label="Ship it", description="explicit wins")
    async def b(*, results): ...

    graph = finalize(wf)
    a_node = graph.nodes["a"]
    assert (a_node.priority, a_node.retries, a_node.timeout) == (0, 1, 600.0)
    assert a_node.label == "a"
    assert a_node.description == "The docstring is the description."
    assert a_node.start is True
    assert a_node.join is False
    b_node = graph.nodes["b"]
    assert b_node.label == "Ship it"
    assert b_node.description == "explicit wins"
    assert (b_node.priority, b_node.retries, b_node.timeout) == (None, None, None)


def test_undocumented_node_has_no_description():
    wf = GraphBuilder("t")

    @wf.node(start=True)
    async def a(): ...

    assert finalize(wf).nodes["a"].description is None


def test_join_node_needs_a_payload_slot():
    wf = GraphBuilder("t")

    @wf.node(start=True)
    async def a(release, /, x): ...

    @wf.node(join=True)
    async def release(): ...

    with pytest.raises(GraphError, match="join"):
        finalize(wf)


def test_join_node_with_a_payload_slot_is_fine():
    wf = GraphBuilder("t")

    @wf.node(start=True)
    async def a(release, /, x): ...

    @wf.node(join=True)
    async def release(*, results): ...

    graph = finalize(wf)
    assert graph.nodes["release"].join is True
    assert graph.nodes["release"].payload_param == "results"


# --- the workflow name rule ------------------------------------------


@pytest.mark.parametrize("name", ["t", "feature_build", "v1_feature", "a0"])
def test_workflow_names_accepted(name: str):
    wf = GraphBuilder(name)

    @wf.node(start=True)
    async def a(): ...

    assert finalize(wf).name == name


@pytest.mark.parametrize(
    "name", ["", "Feature", "feature-build", "1st", "_x", "a b", "abc\n", "\nabc"]
)
def test_workflow_names_rejected(name: str):
    wf = GraphBuilder(name)

    @wf.node(start=True)
    async def a(): ...

    with pytest.raises(GraphError, match="workflow name"):
        finalize(wf)


# --- the built graph is frozen ---------------------------------------


def test_build_freezes():
    wf = GraphBuilder("t")

    @wf.node(start=True)
    async def a(b, /, x): ...

    @wf.node()
    async def b(): ...

    graph = wf.build()
    assert isinstance(graph, Graph)
    assert graph.start == "a"
    assert graph.start_node is graph.nodes["a"]
    with pytest.raises(FrozenInstanceError):
        graph.start = "b"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        graph.nodes["a"].generation = 3  # type: ignore[misc]
    with pytest.raises(TypeError):
        graph.nodes["b"] = graph.nodes["a"]  # type: ignore[index]


def test_finalize_leaves_the_builder_alone():
    """Generations are computed into the graph, not onto the builder."""
    wf = GraphBuilder("t")

    @wf.node(start=True)
    async def a(b, /, x): ...

    @wf.node()
    async def b(): ...

    graph = finalize(wf)
    assert graph.nodes["b"].generation == 1
    assert wf.nodes["b"].generation == 0
    assert finalize(wf).nodes["b"].generation == 1


def test_decorator_returns_the_function_unchanged():
    wf = GraphBuilder("t")

    @wf.node(start=True)
    async def a(): ...

    assert wf.nodes["a"].fn is a


def test_athanore_workflow_is_the_deprecated_alias():
    assert AthanoreWorkflow is GraphBuilder


# --- edge refs and transitions ---------------------------------------


def test_edge_ref_call_returns_a_transition():
    ref = EdgeRef("review")
    assert ref(None) == Transition("review", None)
    assert ref({"ok": True}) == Transition("review", {"ok": True})
    assert ref() == Transition("review", None)
    assert repr(ref) == "<edge review>"


# --- jsonable ---------------------------------------------------------


class _Model(BaseModel):
    n: int
    s: str


@dataclass
class _Point:
    x: int
    y: int


class _Opaque:
    def __repr__(self) -> str:
        return "<opaque>"


def test_jsonable_passes_scalars_through():
    assert jsonable(None) is None
    assert jsonable(3) == 3
    assert jsonable(2.5) == 2.5
    assert jsonable(True) is True
    assert jsonable("s") == "s"


def test_jsonable_pydantic_model():
    assert jsonable(_Model(n=1, s="x")) == {"n": 1, "s": "x"}


def test_jsonable_dataclass():
    assert jsonable(_Point(1, 2)) == {"x": 1, "y": 2}


def test_jsonable_transition():
    assert jsonable(Transition("review", _Point(1, 2))) == {
        "target": "review",
        "payload": {"x": 1, "y": 2},
    }


def test_jsonable_recurses_into_containers():
    assert jsonable({"a": [_Point(1, 2), (3, 4)]}) == {"a": [{"x": 1, "y": 2}, [3, 4]]}


def test_jsonable_falls_back_to_str():
    assert jsonable(_Opaque()) == "<opaque>"
    assert jsonable({"k": _Opaque()}) == {"k": "<opaque>"}

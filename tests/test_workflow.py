"""`Workflow`: the object authors construct (T020, 04 §Programmatic host).

It owns a `GraphBuilder` and caches the graph `finalize()` freezes, so
every reader of a registered workflow gets the same `Graph` object.
"""

import subprocess
import sys

import pytest

from athanore.graph import Graph, GraphError
from athanore.workflow import Workflow


def build_workflow(name: str = "demo") -> Workflow:
    """A two-node workflow: `start` fans nothing, `finish` joins it."""
    wf = Workflow(name)

    @wf.node(start=True, priority=5, retries=2, timeout=30.0, label="Start")
    async def start(finish):
        """Kick it off."""
        return finish("payload")

    @wf.node(join=True, description="the end")
    async def finish(*, result):
        return result

    return wf


def test_name_is_the_builders_name():
    assert Workflow("demo").name == "demo"


def test_finalize_twice_returns_the_same_graph():
    wf = build_workflow()
    first = wf.finalize()
    second = wf.finalize()
    assert isinstance(first, Graph)
    assert first is second


def test_graph_property_is_the_finalized_graph():
    wf = build_workflow()
    graph = wf.finalize()
    assert wf.graph is graph


def test_graph_before_finalize_raises():
    wf = build_workflow()
    with pytest.raises(GraphError, match="not finalized"):
        _ = wf.graph


def test_node_options_round_trip_to_the_graph():
    graph = build_workflow().finalize()

    start = graph.nodes["start"]
    assert start.start is True
    assert start.edges == ("finish",)
    assert start.payload_param is None
    assert start.priority == 5
    assert start.retries == 2
    assert start.timeout == 30.0
    assert start.label == "Start"
    assert start.description == "Kick it off."
    assert start.generation == 0

    finish = graph.nodes["finish"]
    assert finish.join is True
    assert finish.payload_param == "result"
    assert finish.priority is None
    assert finish.retries is None
    assert finish.timeout is None
    assert finish.label == "finish"
    assert finish.description == "the end"
    assert finish.generation == 1


def test_graph_carries_the_workflow_name_and_start():
    graph = build_workflow("other").finalize()
    assert graph.name == "other"
    assert graph.start == "start"
    assert graph.start_node is graph.nodes["start"]


def test_finalize_reports_an_invalid_graph():
    wf = Workflow("broken")

    @wf.node()
    async def orphan():
        return None

    with pytest.raises(GraphError, match="exactly one start node"):
        wf.finalize()


def test_node_after_finalize_is_refused():
    wf = build_workflow()
    wf.finalize()

    with pytest.raises(GraphError, match="already finalized"):

        @wf.node()
        async def late():
            return None


def test_decorator_returns_the_body_unchanged():
    wf = Workflow("demo")

    async def body():
        return None

    decorated = wf.node(start=True)(body)
    assert decorated is body


def test_repr_names_the_workflow_and_its_state():
    wf = build_workflow()
    assert repr(wf) == "<Workflow 'demo' 2 nodes, building>"
    wf.finalize()
    assert repr(wf) == "<Workflow 'demo' 2 nodes, finalized>"


def test_importing_the_module_does_not_import_a_server():
    """`run()` imports `Server` lazily; a lazy import that quietly became
    eager is exactly the regression this catches, so it is asserted in a
    fresh interpreter rather than against pytest's `sys.modules`."""
    probe = (
        "import sys, athanore.workflow;"
        "print(sorted(m for m in sys.modules"
        " if m.split('.')[0] in {'uvicorn', 'fastapi', 'sqlalchemy'}"
        " or m.startswith('athanore.server')"
        " or m.startswith('athanore.api')"
        " or m.startswith('athanore.engine')"
        " or m.startswith('athanore.store')))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "[]", result.stdout

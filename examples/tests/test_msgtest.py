"""`msgtest` on the v1 API: three nodes, two questions, zero agents.

What there is to assert about a workflow with no inference in it is
exactly what it exists to demonstrate: that the graph is three nodes,
that each of the two questions is asked in the mode its surface has to
render, and that both answers reach the run's output and its work log.

The bodies are run with real :class:`~athanore.graph.EdgeRef` arguments
and what comes back goes through
:func:`~athanore.engine.routing.interpret`, as in the other example
suites. ``human_input`` is replaced by name, which is what makes the mode
each call asks for assertable: a body that asked for free text where the
CLI and the SPA expect options would be a fixture that renders the wrong
card.
"""

from __future__ import annotations

import ast
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import msgtest
from athanore.engine.context import TaskContext, bind
from athanore.engine.routing import interpret
from athanore.graph import EdgeRef, Graph, Node
from athanore.plugins.discovery import discover
from athanore.plugins.registry import collect
from athanore.store.rows import LogAuthor, LogKind
from athanore.store.uow import Store
from msgtest import APPROVE, OPTIONS, QUESTION_ONE, QUESTION_TWO, REJECT, wf

GRAPH: Graph = wf.finalize()

PIPELINE: dict[str, tuple[str, ...]] = {
    "ask": ("confirm",),
    "confirm": ("wrap",),
    "wrap": (),
}


def node(name: str) -> Node:
    return GRAPH.nodes[name]


async def route(name: str, payload: Any = None) -> list[tuple[str, Any]]:
    """Run node ``name``'s body and interpret what it returned."""

    one = node(name)
    slot = {one.payload_param: payload} if one.payload_param else {}
    value = await one.fn(*(EdgeRef(edge) for edge in one.edges), **slot)
    return [(step.target, step.payload) for step in interpret(one, value)]


@pytest.fixture
def asked(monkeypatch: pytest.MonkeyPatch) -> Callable[..., list[dict[str, Any]]]:
    """Replace ``human_input`` and script what the operator answers.

    By the name the body reaches for, and recording the whole call — the
    prompt and the mode arguments — because the mode is half of what
    these nodes declare.
    """

    def use(*answers: Any) -> list[dict[str, Any]]:
        calls: list[dict[str, Any]] = []
        replies = list(answers)

        async def ask(prompt: str, **kwargs: Any) -> Any:
            calls.append({"prompt": prompt, **kwargs})
            return replies.pop(0)

        monkeypatch.setattr(msgtest, "human_input", ask)
        return calls

    return use


def test_the_graph_is_three_nodes() -> None:
    """Signature is the graph (rule 1), and `wrap` is the terminal one."""

    assert GRAPH.name == "msgtest"
    assert GRAPH.start == "ask"
    assert {name: one.edges for name, one in GRAPH.nodes.items()} == PIPELINE
    assert [name for name, one in GRAPH.nodes.items() if not one.edges] == ["wrap"]


def test_nothing_here_spawns_a_subprocess() -> None:
    """Zero agents, asserted against the module rather than its docstring.

    The whole value of this example is that it can be run by somebody
    who only wants to see whether a question arrives, so an agent
    reaching it would be the one change that breaks it.
    """

    assert msgtest.__file__ is not None
    tree = ast.parse(Path(msgtest.__file__).read_text(encoding="utf-8"))
    imported = {
        alias.name
        for statement in ast.walk(tree)
        if isinstance(statement, ast.ImportFrom) and statement.module == "athanore"
        for alias in statement.names
    }
    assert imported == {"Workflow", "current_task", "human_input"}


def test_it_declares_no_plugin_surface() -> None:
    """Small on purpose: what this workflow shows is the message channel."""

    spec = collect(wf)
    assert (spec.routes, spec.actions, spec.panels, spec.handlers) == ((), (), (), ())


def test_no_node_retries() -> None:
    """A body whose only failure is a wait nobody answered is not retried.

    A *crash* is a different thing and is not a retry: a re-executed
    attempt re-attaches to the request it already opened, by ordinal, and
    is handed the answer that is already there (06 §Restart durability).
    """

    assert [one.retries for one in GRAPH.nodes.values()] == [0, 0, 0]


def test_the_answers_are_the_only_payloads() -> None:
    """Two of three nodes take a payload, and both take it keyword-only."""

    slots = {name: one.payload_param for name, one in GRAPH.nodes.items()}
    assert slots == {"ask": None, "confirm": "word", "wrap": "answers"}
    assert "word" not in node("confirm").edges
    assert "answers" not in node("wrap").edges


async def test_the_first_question_is_free_text(
    asked: Callable[..., list[dict[str, Any]]],
) -> None:
    """No mode arguments, so the answer is whatever was typed (06)."""

    calls = asked("athanor")
    assert await route("ask") == [("confirm", "athanor")]
    assert calls == [{"prompt": QUESTION_ONE}]


async def test_the_second_question_is_a_choice_over_the_first_answer(
    asked: Callable[..., list[dict[str, Any]]],
) -> None:
    """`options=` is the mode the CLI and the SPA render as buttons."""

    calls = asked(APPROVE)
    assert await route("confirm", "athanor") == [
        ("wrap", {"word": "athanor", "verdict": APPROVE})
    ]
    assert calls == [
        {
            "prompt": QUESTION_TWO.format(word="athanor"),
            "options": OPTIONS,
        }
    ]
    assert OPTIONS == [APPROVE, REJECT]
    # The word the operator chose is shown back to them, which is the
    # whole point of a second question.
    assert "'athanor'" in calls[0]["prompt"]


async def test_the_run_ends_with_both_answers_and_says_so_in_the_log(
    store: Store, context: Callable[..., Any]
) -> None:
    """No edges, so what `wrap` returns is the run's output (04)."""

    ctx: TaskContext = await context(node="wrap")
    payload = {"word": "athanor", "verdict": REJECT}
    with bind(ctx):
        assert await route("wrap", payload) == []
    async with store.uow() as uow:
        written = await uow.log.list(ctx.run_id)
    assert [(entry.author, entry.kind) for entry in written] == [
        (LogAuthor.engine, LogKind.deliverable)
    ]
    assert written[0].text == "secret word: athanor; operator verdict: reject"
    # And the value the body returns is what the run ends as: no edges,
    # so `interpret` had nothing to enqueue and the return is the output.
    with bind(ctx):
        assert await node("wrap").fn(answers=payload) == payload


async def test_a_task_moved_onto_wrap_by_hand_records_what_there_is(
    store: Store, context: Callable[..., Any]
) -> None:
    """An answer nobody gave is empty, not a `KeyError` (04 §Routing edge cases)."""

    ctx: TaskContext = await context(node="wrap")
    with bind(ctx):
        assert await node("wrap").fn(answers=None) == {"word": "", "verdict": ""}


def test_athanore_serve_discovers_msgtest() -> None:
    """`athanore serve` needs to be told nothing (09 §Discovery)."""

    found = {workflow.name: workflow for workflow in discover()}
    assert found["msgtest"] is wf

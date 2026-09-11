"""Swapping a workflow's graph on a running engine (T083, 22 §Replace).

Two facts, both consequences of how the runner already works rather
than of anything new:

- **an attempt in flight finishes on the graph it started with**, routing
  included, because ``_load_graph`` read the registry at the claim and
  the attempt holds that object; nothing reaches into a coroutine to
  change what it is executing;
- **the next task dispatches on the new graph**, because the runner
  looks the graph up by name at every claim — so a task whose node the
  replacement lacks dead-letters with the existing ``GraphError``
  (D42), exactly as it would after an edit and a restart.

The pool half is the one rule ``replace`` adds: a *different* pool is
refused while any attempt of the workflow is in flight, because the
leases those attempts hold belong to the pool they were claimed on (22
§Pools), and rebinds the name otherwise. The check is exact because it
runs between ticks (``Scheduler.quiescent``).
"""

from __future__ import annotations

import asyncio

import pytest

from athanore.engine import Engine
from athanore.engine.context import current_task
from athanore.engine.pools import Pool
from athanore.store.rows import RunStatus, TaskRow, TaskStatus
from athanore.store.uow import Store
from athanore.workflow import Workflow

# --------------------------------------------------------------------------
# Versions of one workflow
# --------------------------------------------------------------------------

NAME = "versioned"


class Version:
    """One edition of the workflow: ``top`` parks, then routes; ``bottom`` marks.

    Every body appends ``(node, tag)`` to a shared list, so which
    *edition's* body ran a node is a fact the test reads back rather
    than infers. ``top`` routes to ``bottom``; ``other`` exists so a
    later edition can route ``top`` elsewhere and the old attempt's
    routing can be told from the new graph's.
    """

    def __init__(self, tag: str, marks: list[tuple[str, str]]) -> None:
        self.tag = tag
        self.marks = marks
        self.started = asyncio.Event()
        self.go = asyncio.Event()

    def workflow(self, *, route_to_other: bool = False) -> Workflow:
        wf = Workflow(NAME)
        tag, marks = self.tag, self.marks

        @wf.node(start=True)
        async def top(bottom, other):  # type: ignore[no-untyped-def]
            marks.append(("top", tag))
            self.started.set()
            await self.go.wait()
            return other if route_to_other else bottom

        @wf.node()
        async def bottom() -> str:
            marks.append(("bottom", tag))
            return "landed"

        @wf.node()
        async def other() -> str:
            marks.append(("other", tag))
            return "elsewhere"

        return wf

    def without_bottom(self) -> Workflow:
        """The edition that renamed ``bottom``: a task for it has no node."""

        wf = Workflow(NAME)
        tag, marks = self.tag, self.marks

        @wf.node(start=True)
        async def top(renamed):  # type: ignore[no-untyped-def]
            marks.append(("top", tag))
            self.started.set()
            await self.go.wait()
            return renamed

        @wf.node()
        async def renamed() -> str:
            marks.append(("renamed", tag))
            return "landed"

        return wf


class Asker:
    """A body that parks on a human, so the attempt reads ``waiting``."""

    def __init__(self) -> None:
        self.parked = asyncio.Event()
        self.answered = asyncio.Event()

    def workflow(self, name: str = "asks") -> Workflow:
        wf = Workflow(name)

        @wf.node(start=True)
        async def only() -> str:
            ctx = current_task()
            async with ctx.services.lease.released(7):
                self.parked.set()
                await self.answered.wait()
            return "answered"

        return wf


async def tasks_of(store: Store, run_id: str) -> list[TaskRow]:
    async with store.reader() as reader:
        return await reader.tasks.list_for_run(run_id)


async def at(store: Store, run_id: str, node: str) -> list[TaskRow]:
    return [task for task in await tasks_of(store, run_id) if task.node == node]


# --------------------------------------------------------------------------
# The graph the next claim sees, and the one the attempt keeps
# --------------------------------------------------------------------------


async def test_the_attempt_in_flight_keeps_its_body_and_the_next_task_takes_the_new(
    start_engine, store: Store, run_to_completion, wait_for
) -> None:
    """22 §Replace: old body to the end, routing included; new graph next.

    The second edition's ``top`` routes to ``other``; the first
    edition's attempt, already inside its body, still routes to
    ``bottom`` — and the ``bottom`` that then runs is the second
    edition's.
    """

    marks: list[tuple[str, str]] = []
    first, second = Version("v1", marks), Version("v2", marks)
    engine: Engine = await start_engine(first.workflow())
    run = await engine.ops.submit(NAME, "a run")
    await wait_for(first.started)

    await engine.replace(second.workflow(route_to_other=True).finalize())
    assert engine.graphs[NAME].name == NAME
    first.go.set()

    assert (await run_to_completion(run.id)).status is RunStatus.completed
    assert marks == [("top", "v1"), ("bottom", "v2")]
    assert await at(store, run.id, "other") == []
    (bottom,) = await at(store, run.id, "bottom")
    assert bottom.status is TaskStatus.done


async def test_a_task_whose_node_the_replacement_lacks_dead_letters(
    start_engine, store: Store, run_to_completion, wait_for
) -> None:
    """D42, live: the old attempt enqueues ``bottom``; the new graph has none."""

    marks: list[tuple[str, str]] = []
    first, second = Version("v1", marks), Version("v2", marks)
    engine: Engine = await start_engine(first.workflow())
    run = await engine.ops.submit(NAME, "a run")
    await wait_for(first.started)

    await engine.replace(second.without_bottom().finalize())
    first.go.set()

    assert (await run_to_completion(run.id)).status is RunStatus.failed
    (bottom,) = await at(store, run.id, "bottom")
    assert bottom.status is TaskStatus.dead_letter
    assert bottom.error is not None and bottom.error.startswith("GraphError(")
    assert "has no node 'bottom'" in bottom.error
    assert marks == [("top", "v1")]


async def test_a_run_submitted_after_the_swap_runs_the_new_edition_throughout(
    start_engine, run_to_completion
) -> None:
    marks: list[tuple[str, str]] = []
    first, second = Version("v1", marks), Version("v2", marks)
    engine: Engine = await start_engine(first.workflow())

    await engine.replace(second.workflow().finalize())
    second.go.set()
    run = await engine.ops.submit(NAME, "a run")

    assert (await run_to_completion(run.id)).status is RunStatus.completed
    assert marks == [("top", "v2"), ("bottom", "v2")]


async def test_replace_refuses_an_unregistered_name(engines) -> None:
    engine: Engine = engines()
    with pytest.raises(KeyError, match="'versioned' is not registered"):
        await engine.replace(Version("v1", []).workflow().finalize())
    assert engine.graphs == {}


# --------------------------------------------------------------------------
# The pool binding
# --------------------------------------------------------------------------


async def test_a_pool_move_is_refused_while_an_attempt_is_running(
    start_engine, run_to_completion, wait_for
) -> None:
    marks: list[tuple[str, str]] = []
    first, second = Version("v1", marks), Version("v2", marks)
    engine: Engine = await start_engine((first.workflow(), Pool("here", 1)))
    engine.pools.add(Pool("there", 1))
    run = await engine.ops.submit(NAME, "a run")
    await wait_for(first.started)
    old_graph = engine.graphs[NAME]

    with pytest.raises(ValueError, match="cannot move from pool 'here' to 'there'"):
        await engine.replace(second.workflow().finalize(), pool="there")

    # A refusal leaves the engine exactly as it was.
    assert engine.graphs[NAME] is old_graph
    assert engine.pools.for_workflow(NAME).name == "here"
    assert engine.pools.workflows_of("there") == ()

    # ...and the same move is accepted once nothing is in flight.
    first.go.set()
    await run_to_completion(run.id)
    await engine.replace(second.workflow().finalize(), pool=Pool("there", 99))
    assert engine.pools.for_workflow(NAME).name == "there"
    assert engine.pools.workflows_of("here") == ()
    assert engine.pools.workflows_of("there") == (NAME,)
    # The `Pool` object contributed its name and nothing else.
    assert engine.pools.get("there").capacity == 1
    assert engine.graphs[NAME] is not old_graph


async def test_a_pool_move_is_refused_while_an_attempt_is_waiting_on_a_human(
    start_engine, run_to_completion, wait_for
) -> None:
    """A parked attempt is in flight: its row reads ``waiting``, and it counts."""

    asker = Asker()
    engine: Engine = await start_engine((asker.workflow(), Pool("here", 1)))
    engine.pools.add(Pool("there", 1))
    run = await engine.ops.submit("asks", "a run")
    await wait_for(asker.parked)
    assert engine.attempts_of("asks") == [
        task.id for task in await _all(engine, run.id)
    ]

    with pytest.raises(ValueError, match="with attempts in flight"):
        await engine.replace(asker.workflow().finalize(), pool="there")
    assert engine.pools.for_workflow("asks").name == "here"

    asker.answered.set()
    await run_to_completion(run.id)
    await engine.replace(asker.workflow().finalize(), pool="there")
    assert engine.pools.for_workflow("asks").name == "there"


async def test_the_same_pool_is_not_a_move_and_is_never_refused(
    start_engine, run_to_completion, wait_for
) -> None:
    marks: list[tuple[str, str]] = []
    first, second = Version("v1", marks), Version("v2", marks)
    engine: Engine = await start_engine((first.workflow(), Pool("here", 1)))
    run = await engine.ops.submit(NAME, "a run")
    await wait_for(first.started)

    await engine.replace(second.workflow().finalize(), pool="here")
    assert engine.pools.for_workflow(NAME).name == "here"
    first.go.set()

    assert (await run_to_completion(run.id)).status is RunStatus.completed
    assert marks == [("top", "v1"), ("bottom", "v2")]


async def test_an_unknown_pool_is_a_lookup_error_and_is_never_created(
    start_engine, wait_for
) -> None:
    """Checked before the in-flight refusal: a typo is reported as a typo."""

    marks: list[tuple[str, str]] = []
    first, second = Version("v1", marks), Version("v2", marks)
    engine: Engine = await start_engine((first.workflow(), Pool("here", 1)))
    await engine.ops.submit(NAME, "a run")
    await wait_for(first.started)
    old_graph = engine.graphs[NAME]

    with pytest.raises(KeyError, match="no pool named 'nope'"):
        await engine.replace(second.workflow().finalize(), pool=Pool("nope", 1))

    assert "nope" not in engine.pools
    assert engine.graphs[NAME] is old_graph
    assert engine.pools.for_workflow(NAME).name == "here"
    first.go.set()


async def _all(engine: Engine, run_id: str) -> list[TaskRow]:
    return await tasks_of(engine.store, run_id)

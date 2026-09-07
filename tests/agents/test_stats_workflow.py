"""One stats entry per agent run, over a whole workflow (T040).

`docs/porting-ledger.md`: the MVP's ``test_stats_workflow.py``. The
suites either side of this one pin the pieces — ``test_stats_unit.py``
builds an entry and records it against one context, and
``test_acp_outcomes.py`` shows a real ACP run producing exactly one entry
on each of its five exits — and this is the file that says they compose
under the engine: several agent runs, across several nodes, with a retry
in the middle.

Four things are asserted here that no smaller test can see:

- **one entry per agent run, and they are told apart.** A retried node
  runs its agent twice, so ``(node, attempt)`` has to identify an entry;
  a ``finally`` that recorded once per *task* would look right at every
  other level and lose one here.
- **a failed run is still accounted for.** The engine's retry does not
  erase what the attempt cost: the failed attempt carries its reason and
  the tokens it did spend.
- **the three destinations agree.** 05 §Stats entry names a work-log
  line, an ``agent.stats`` event and the ``tasks.stats`` column (D46), and
  a reader that saw two of the three would be reading a half-written
  fact.
- **nothing else grows a stats entry.** A node body that fails without
  an agent in it produces the scheduler's failure line and no entry at
  all — stats are about agent runs, and inventing one for a body that
  raised would put a row in the run's totals that measures nothing.

The doubles are :class:`~athanore.testing.StatsMockAgent`: no subprocess,
but the entry is built by ``build_entry`` and written by ``record_entry``,
which is the path the ACP façade takes from its own ``finally``.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any, Final

import pytest

from athanore.engine import Engine
from athanore.events.bus import EventBus
from athanore.events.names import EventName
from athanore.settings import AthanoreSettings
from athanore.store.rows import LogAuthor, LogEntryRow, LogKind, RunRow, RunStatus
from athanore.store.uow import Store
from athanore.testing import StatsMockAgent
from athanore.workflow import Workflow

#: How long a run of four nodes gets before the test calls it deadlocked.
DEADLINE: Final = 10.0

#: The engine's dispatch tick. Every path that makes work ready notifies,
#: so this is the safety net rather than the mechanism.
TICK: Final = 0.02

#: ``[stats] node=build attempt=2 …`` — the two fields that identify one
#: agent run in a work log full of them.
HEAD = re.compile(r"\[stats\] node=(\S+) attempt=(\d+)")


def pair(text: str) -> tuple[str, int]:
    """The ``(node, attempt)`` a ``[stats]`` line belongs to."""

    head = HEAD.match(text)
    assert head is not None, text
    return head.group(1), int(head.group(2))


@pytest.fixture
def settings(tmp_path: Path, db_url: str) -> AthanoreSettings:
    """The engine's settings, every field this suite reads passed by hand.

    Constructed explicitly so an ``ATHANORE_*`` variable in the shell
    that started the container cannot change what is asserted —
    ``workers`` in particular, which sizes the default pool.
    """

    return AthanoreSettings(
        root_path=tmp_path,
        db_url=db_url,
        public_url="http://127.0.0.1:4002",
        workers=1,
        max_retries=3,
        stream_flush_interval=0.05,
    )


@pytest.fixture
async def running(
    settings: AthanoreSettings, store: Store, bus: EventBus
) -> AsyncIterator[Callable[[Workflow], Any]]:
    """Register a workflow on a real, started engine, and stop it after.

    The teardown is the point: an engine left started keeps a dispatch
    loop claiming against the next test's database.
    """

    started: list[Engine] = []

    async def start(workflow: Workflow) -> Engine:
        engine = Engine(settings, store, bus, tick=TICK)
        engine.register(workflow.finalize())
        started.append(engine)
        await engine.start()
        return engine

    yield start
    for engine in started:
        await engine.stop()


@pytest.fixture
def finished(store: Store, bus: EventBus) -> Callable[[str], Any]:
    """Wait for a run to end, and answer with the row it ended as.

    The bus rather than a poll, and the subscription is taken before the
    first read, so a run that ended between the submission and this call
    is seen in the store instead of waited for forever.
    """

    async def wait(run_id: str) -> RunRow:
        subscription = bus.subscribe(
            [EventName.run_completed.value, EventName.run_failed.value]
        )
        try:
            async with asyncio.timeout(DEADLINE):
                while True:
                    async with store.reader() as reader:
                        row = await reader.runs.get(run_id)
                    if row is not None and row.status in (
                        RunStatus.completed,
                        RunStatus.failed,
                    ):
                        return row
                    await subscription.queue.get()
        finally:
            subscription.close()

    return wait


async def log_of(store: Store, run_id: str) -> list[LogEntryRow]:
    async with store.reader() as reader:
        return await reader.log.list(run_id)


async def stats_entries(store: Store, run_id: str) -> list[LogEntryRow]:
    """The run's ``[stats]`` lines: one per agent run, and no more."""

    entries = await log_of(store, run_id)
    return [entry for entry in entries if entry.kind == LogKind.stats]


async def stats_events(store: Store, run_id: str) -> list[dict[str, Any]]:
    async with store.reader() as reader:
        rows = await reader.events.list_for_run(run_id)
    return [dict(row.data) for row in rows if row.name == EventName.agent_stats]


async def columns(store: Store, run_id: str) -> dict[tuple[str, int], dict[str, Any]]:
    """The ``tasks.stats`` column of every task of the run that has one."""

    async with store.reader() as reader:
        tasks = await reader.tasks.list_for_run(run_id)
    return {
        (task.node, task.attempt): task.stats
        for task in tasks
        if task.stats is not None
    }


# --------------------------------------------------------------------------
# A pipeline of agent runs, one of which fails and is retried
# --------------------------------------------------------------------------


def pipeline() -> Workflow:
    """Four agent nodes; ``build`` fails its first attempt and is retried.

    Each seat scripts what a provider would have supplied — the model,
    the cost, the tool-call count, the session it ran in — and appends
    its deliverable to the work log, so the stats lines have to coexist
    with the channel the next stage actually reads (D4).
    """

    wf = Workflow("statspipe")
    attempts = {"build": 0}

    @wf.node(start=True)
    async def start(build):
        await StatsMockAgent(
            stats={
                "model": "fake/m1",
                "cost": 0.0,
                "tool_calls": 1,
                "session_id": "01a0start0-0000-0000-0000-000000000000",
                "input_tokens": 10,
                "output_tokens": 5,
                "total_tokens": 15,
            },
            log="intake: reworded the brief",
        ).run()
        return build

    @wf.node()
    async def build(review):
        attempts["build"] += 1
        if attempts["build"] == 1:
            await StatsMockAgent(
                stats={
                    "tool_calls": 2,
                    "session_id": "01a0build1-0000-0000-0000-000000000000",
                    "input_tokens": 7,
                    "output_tokens": 3,
                    "total_tokens": 10,
                },
                fail="timeout",
            ).run()
        await StatsMockAgent(
            stats={
                "model": "fake/m1",
                "cost": 0.0,
                "tool_calls": 3,
                "session_id": "01a0build2-0000-0000-0000-000000000000",
                "input_tokens": 8,
                "output_tokens": 4,
                "total_tokens": 12,
            },
            log="engineering: built it, tests green",
        ).run()
        return review

    @wf.node()
    async def review(ship):
        await StatsMockAgent(
            stats={
                "session_id": "01a0review-0000-0000-0000-000000000000",
                "input_tokens": 11,
                "output_tokens": 2,
                "total_tokens": 13,
            },
            log="review: approved",
        ).run()
        return ship

    @wf.node()
    async def ship():
        await StatsMockAgent(
            stats={
                "model": "fake/m1",
                "cost": 0.0001,
                "tool_calls": 1,
                "session_id": "01a0ship00-0000-0000-0000-000000000000",
                "input_tokens": 2,
                "output_tokens": 1,
                "total_tokens": 3,
            },
            log="git: shipped it",
        ).run()

    return wf


#: What the run above is expected to have accounted for: five agent runs
#: over four nodes, because ``build`` ran twice.
RUNS: Final = {
    ("start", 1),
    ("build", 1),
    ("build", 2),
    ("review", 1),
    ("ship", 1),
}


@pytest.fixture
async def pipeline_run(running: Any, finished: Any) -> str:
    """One completed run of :func:`pipeline`, as its run id."""

    engine: Engine = await running(pipeline())
    submitted = await engine.ops.submit("statspipe", "stats run", "d")
    run = await finished(submitted.id)
    assert run.status == RunStatus.completed, run
    return submitted.id


async def test_every_agent_run_is_accounted_for_exactly_once(
    store: Store, pipeline_run: str
) -> None:
    """Five agent runs, five entries, each one identifiable."""

    entries = await stats_entries(store, pipeline_run)
    assert len(entries) == 5, [entry.text for entry in entries]
    assert {pair(entry.text) for entry in entries} == RUNS
    assert {entry.author for entry in entries} == {LogAuthor.engine}


async def test_the_retried_attempt_keeps_its_own_numbers(
    store: Store, pipeline_run: str
) -> None:
    """A failed attempt is accounted for, with its reason and its tokens."""

    entries = await stats_entries(store, pipeline_run)
    by_run = {pair(entry.text): entry.text for entry in entries}
    assert "failed (timeout)" in by_run[("build", 1)]
    assert "tokens=7 in / 3 out / 10 total" in by_run[("build", 1)]
    assert "tools=2 calls" in by_run[("build", 1)]

    succeeded = by_run[("build", 2)]
    assert " ok — " in succeeded
    assert "model=fake/m1" in succeeded
    assert "cost=$0.0000" in succeeded
    assert "tools=3 calls" in succeeded


async def test_the_deliverables_are_untouched_beside_them(
    store: Store, pipeline_run: str
) -> None:
    """The work log is the inter-stage channel; stats only add to it (D4)."""

    entries = await log_of(store, pipeline_run)
    written = [entry.text for entry in entries if entry.author == LogAuthor.agent]
    assert written == [
        "intake: reworded the brief",
        "engineering: built it, tests green",
        "review: approved",
        "git: shipped it",
    ]

    failures = [entry.text for entry in entries if entry.kind == LogKind.failure]
    assert any(text.startswith("attempt 1 failed:") for text in failures), failures


async def test_the_event_stream_carries_one_of_each(
    store: Store, pipeline_run: str
) -> None:
    """18's ``agent.stats``, once per agent run, saying the same thing."""

    events = await stats_events(store, pipeline_run)
    assert {(event["node"], event["attempt"]) for event in events} == RUNS
    assert len(events) == 5

    by_run = {(event["node"], event["attempt"]): event for event in events}
    assert by_run[("build", 1)]["status"] == "failed"
    assert by_run[("build", 1)]["reason"] == "timeout"
    assert [event["status"] for event in events].count("ok") == 4
    # Unknowns stay unknown all the way out to the consumer.
    assert "cost" not in by_run[("review", 1)]
    assert "model" not in by_run[("review", 1)]


async def test_the_column_the_totals_are_summed_from_is_written(
    store: Store, pipeline_run: str
) -> None:
    """D46: a run's totals are a ``SUM`` over ``tasks.stats``."""

    written = await columns(store, pipeline_run)
    assert set(written) == RUNS
    assert written[("build", 1)]["reason"] == "timeout"
    assert sum(entry.get("tool_calls", 0) for entry in written.values()) == 7
    assert sum(entry.get("input_tokens", 0) for entry in written.values()) == 38


# --------------------------------------------------------------------------
# A failure with no agent in it
# --------------------------------------------------------------------------


def bare() -> Workflow:
    """One node that raises, with no agent anywhere in the body."""

    wf = Workflow("bare")

    @wf.node(start=True)
    async def boom() -> str:
        raise RuntimeError("not an agent run")

    return wf


async def test_a_failure_with_no_agent_gets_no_entry(
    running: Any, finished: Any, store: Store
) -> None:
    """Stats are about agent runs; a body that raised measured nothing."""

    engine: Engine = await running(bare())
    submitted = await engine.ops.submit("bare", "bare failure", "d")
    run = await finished(submitted.id)
    assert run.status == RunStatus.failed, run

    entries = await log_of(store, submitted.id)
    assert any(
        entry.kind == LogKind.failure and entry.text.endswith("not an agent run")
        for entry in entries
    ), [entry.text for entry in entries]

    assert await stats_entries(store, submitted.id) == []
    assert await stats_events(store, submitted.id) == []
    assert await columns(store, submitted.id) == {}

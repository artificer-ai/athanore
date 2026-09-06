"""Tests for :mod:`athanore.store.repos.runs`.

Four properties carry this module. The first is that a run list is
**one** query: ``current_nodes`` and ``pending_requests`` are correlated
subqueries, and the difference between that and a loop is invisible until
the list has a hundred runs on it, so it is asserted with a statement
counter rather than by reading the SQL. The second is that ordering
arithmetic — append at ``max + 1``, swap, move, compact — leaves the
positions a permutation of ``1..n`` with no gaps and no duplicates. The
third is that :class:`~athanore.store.rows.RunStats` stays honest: a run
whose attempts recorded nothing reports ``None``, never zero. The fourth
is that deleting a run really does take everything with it, events
included — those have no foreign key, so the cascade cannot be trusted to
do it (D83).

Every test runs on SQLite; T014b parametrises the suite over
PostgreSQL too (``tests/store/conftest.py``).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import AsyncEngine

from athanore.store.repos.runs import (
    current_nodes_expression,
    list_statement,
    stats_statement,
    stats_value,
)
from athanore.store.rows import (
    LogAuthor,
    RunStatus,
    TaskStatus,
)
from athanore.store.tables import (
    answers,
    events,
    log_entries,
    requests,
    runs,
    stream_chunks,
    submissions,
    tasks,
)
from athanore.store.uow import Store, now

NOW = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


async def make_run(store: Store, workflow: str = "demo", title: str = "a run") -> str:
    async with store.uow() as uow:
        run = await uow.runs.insert(workflow, title)
    return run.id


async def add_task(
    store: Store,
    run_id: str,
    node: str,
    status: TaskStatus = TaskStatus.in_progress,
    attempt: int = 1,
    stats: dict[str, Any] | None = None,
    finished: datetime | None = None,
) -> int:
    async with store.uow() as uow:
        result = await uow.conn.execute(
            tasks.insert()
            .values(
                run_id=run_id,
                node=node,
                attempt=attempt,
                status=status.value,
                priority=0,
                stats=stats,
                created=NOW,
                finished=finished,
                terminal=False,
                branch=[],
            )
            .returning(tasks.c.id)
        )
        return int(result.scalar_one())


async def add_request(store: Store, run_id: str, task_id: int) -> int:
    async with store.uow() as uow:
        result = await uow.conn.execute(
            requests.insert()
            .values(
                run_id=run_id,
                task_id=task_id,
                prompt="may I?",
                mode="options",
                source="agent",
                kind="permission",
                created=NOW,
            )
            .returning(requests.c.id)
        )
        return int(result.scalar_one())


async def answer_request(store: Store, request_id: int) -> None:
    async with store.uow() as uow:
        await uow.conn.execute(
            answers.insert().values(
                request_id=request_id,
                author="user",
                option_id="allow",
                consumed=False,
                created=NOW,
            )
        )


async def add_children(store: Store, run_id: str, task_id: int) -> None:
    """A log entry, a submission and a transcript chunk under one task.

    T014a and T014b give these tables repositories; the cascade is T014's
    to prove, so the rows go in through the connection.
    """

    async with store.uow() as uow:
        await uow.conn.execute(
            log_entries.insert().values(
                run_id=run_id,
                task_id=task_id,
                node="build",
                author=LogAuthor.engine.value,
                kind=None,
                text="started",
                created=NOW,
            )
        )
        await uow.conn.execute(
            submissions.insert().values(
                task_id=task_id, payload={"value": 1}, created=NOW
            )
        )
        await uow.conn.execute(
            stream_chunks.insert().values(
                task_id=task_id, seq=1, kind="text", text="hello", created=NOW
            )
        )


async def add_event(
    store: Store, name: str, run_id: str | None, task_id: int | None
) -> None:
    """One row in the table with no foreign key (D83)."""

    async with store.uow() as uow:
        await uow.conn.execute(
            events.insert().values(
                run_id=run_id,
                task_id=task_id,
                name=name,
                data={},
                created=NOW + timedelta(seconds=1),
            )
        )


async def insert_run_at(store: Store, run_id: str, title: str, position: int) -> str:
    """A run with a chosen id and position, bypassing ``RunRepo.insert``.

    ``insert`` appends at ``max + 1`` and mints a ULID, so it cannot make
    the duplicated positions and the id/rowid disagreement that the
    compaction tests need.
    """

    async with store.uow() as uow:
        await uow.conn.execute(
            runs.insert().values(
                id=run_id,
                workflow="demo",
                title=title,
                description="",
                status=RunStatus.queued.value,
                output=None,
                position=position,
                created=NOW,
                updated=NOW,
                finished=None,
            )
        )
    return run_id


async def positions(store: Store) -> list[tuple[str, int]]:
    """Every run as ``(title, position)`` in list order."""

    async with store.reader() as reader:
        return [(run.title, run.position) for run in await reader.runs.list()]


async def count_rows(store: Store, table: Any, **where: Any) -> int:
    async with store.read() as conn:
        statement = select(func.count()).select_from(table)
        for column, value in where.items():
            statement = statement.where(table.c[column] == value)
        return int((await conn.execute(statement)).scalar_one())


class Counter:
    """Counts the statements a block sends to the database."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine.sync_engine
        self.statements: list[str] = []

    def _record(
        self,
        conn: object,
        cursor: object,
        statement: str,
        *rest: object,
    ) -> None:
        self.statements.append(statement)

    def __enter__(self) -> Counter:
        event.listen(self._engine, "before_cursor_execute", self._record)
        return self

    def __exit__(self, *exc: object) -> None:
        event.remove(self._engine, "before_cursor_execute", self._record)


# --------------------------------------------------------------------------
# insert
# --------------------------------------------------------------------------


async def test_insert_gives_a_queued_run_at_the_bottom(store: Store) -> None:
    async with store.uow() as uow:
        first = await uow.runs.insert("demo", "first", "the first one")
        second = await uow.runs.insert("demo", "second")

    assert first.status is RunStatus.queued
    assert first.description == "the first one"
    assert second.description == ""
    assert (first.position, second.position) == (1, 2)
    assert first.finished is None
    assert first.created == first.updated
    assert first.created.tzinfo is not None


async def test_insert_appends_at_max_position_plus_one(store: Store) -> None:
    ids = [await make_run(store, title=f"run {index}") for index in range(3)]
    async with store.uow() as uow:
        assert await uow.runs.delete(ids[1]) is True
        appended = await uow.runs.insert("demo", "appended")

    assert appended.position == 4


async def test_ids_are_ulids_and_unique(store: Store) -> None:
    async with store.uow() as uow:
        made = [await uow.runs.insert("demo", str(index)) for index in range(3)]

    assert len({run.id for run in made}) == 3
    for run in made:
        assert len(run.id) == 26
        assert run.id.isalnum() and run.id.isupper()


# --------------------------------------------------------------------------
# get
# --------------------------------------------------------------------------


async def test_get_reads_the_run_back(store: Store) -> None:
    run_id = await make_run(store, title="readable")

    async with store.reader() as reader:
        run = await reader.runs.get(run_id)

    assert run is not None
    assert (run.id, run.title, run.workflow) == (run_id, "readable", "demo")


async def test_get_of_an_unknown_run_is_none(store: Store) -> None:
    async with store.reader() as reader:
        assert await reader.runs.get("01JNOSUCHRUN") is None


# --------------------------------------------------------------------------
# list
# --------------------------------------------------------------------------


async def test_list_is_in_position_order(store: Store) -> None:
    for title in ("a", "b", "c"):
        await make_run(store, title=title)

    assert await positions(store) == [("a", 1), ("b", 2), ("c", 3)]


async def test_list_filters_by_status_and_workflow(store: Store) -> None:
    first = await make_run(store, workflow="alpha", title="a")
    await make_run(store, workflow="beta", title="b")
    async with store.uow() as uow:
        await uow.runs.set_status(first, RunStatus.running)

    async with store.reader() as reader:
        running = await reader.runs.list(status=RunStatus.running)
        beta = await reader.runs.list(workflow="beta")
        both = await reader.runs.list(status=RunStatus.queued, workflow="beta")

    assert [run.title for run in running] == ["a"]
    assert [run.title for run in beta] == ["b"]
    assert [run.title for run in both] == ["b"]


async def test_list_aggregates_in_flight_nodes_and_open_requests(
    store: Store,
) -> None:
    """A fan-out puts a run in two nodes at once, with one request open."""

    run_id = await make_run(store, title="busy")
    build = await add_task(store, run_id, "build", TaskStatus.in_progress)
    await add_task(store, run_id, "review", TaskStatus.waiting)
    # A second attempt of a node already counted: the aggregate is DISTINCT.
    await add_task(store, run_id, "build", TaskStatus.in_progress, attempt=2)
    # Neither of these is in flight, so neither contributes a node.
    await add_task(store, run_id, "plan", TaskStatus.done)
    await add_task(store, run_id, "spike", TaskStatus.dead_letter)
    await add_request(store, run_id, build)
    await make_run(store, title="quiet")

    async with store.reader() as reader:
        listed = {run.title: run for run in await reader.runs.list()}

    assert listed["busy"].current_nodes == ["build", "review"]
    assert listed["busy"].pending_requests == 1
    assert listed["quiet"].current_nodes == []
    assert listed["quiet"].pending_requests == 0
    assert listed["busy"].unregistered is False


async def test_list_counts_neither_answered_nor_stale_requests(
    store: Store,
) -> None:
    run_id = await make_run(store, title="asking")
    live = await add_task(store, run_id, "build", TaskStatus.in_progress)
    finished = await add_task(store, run_id, "plan", TaskStatus.done)
    await add_request(store, run_id, live)
    answered = await add_request(store, run_id, live)
    await answer_request(store, answered)
    # Unanswered, but its task is finished: stale, not pending (03).
    await add_request(store, run_id, finished)

    async with store.reader() as reader:
        (summary,) = await reader.runs.list()

    assert summary.pending_requests == 1


async def test_list_does_not_leak_another_runs_tasks(store: Store) -> None:
    await make_run(store, title="mine")
    theirs = await make_run(store, title="theirs")
    await add_task(store, theirs, "build", TaskStatus.in_progress)

    async with store.reader() as reader:
        listed = {run.title: run for run in await reader.runs.list()}

    assert listed["mine"].current_nodes == []
    assert listed["theirs"].current_nodes == ["build"]


async def test_list_is_one_statement_however_many_runs(
    store: Store, engine: AsyncEngine
) -> None:
    """Not N+1: the aggregates are subqueries, not a second round trip."""

    for index in range(5):
        run_id = await make_run(store, title=f"run {index}")
        task_id = await add_task(store, run_id, "build", TaskStatus.in_progress)
        await add_request(store, run_id, task_id)

    async with store.reader() as reader:
        with Counter(engine) as counter:
            listed = await reader.runs.list()

    assert len(listed) == 5
    assert len(counter.statements) == 1


# --------------------------------------------------------------------------
# detail
# --------------------------------------------------------------------------


async def test_detail_returns_the_run_its_attempts_and_the_totals(
    store: Store,
) -> None:
    run_id = await make_run(store, title="detailed")
    await add_task(
        store,
        run_id,
        "build",
        TaskStatus.failed,
        attempt=1,
        stats={
            "input_tokens": 100,
            "output_tokens": 10,
            "total_tokens": 110,
            "tool_calls": 2,
            "cost": 0.25,
            "duration_s": 1.5,
        },
    )
    await add_task(
        store,
        run_id,
        "build",
        TaskStatus.done,
        attempt=2,
        stats={
            "input_tokens": 200,
            "output_tokens": 20,
            "total_tokens": 220,
            "tool_calls": 3,
            "cost": 0.5,
            "duration_s": 2.5,
        },
    )
    # An attempt that recorded nothing must not drag a total to zero.
    await add_task(store, run_id, "review", TaskStatus.ready, stats=None)

    async with store.reader() as reader:
        detail = await reader.runs.detail(run_id)

    assert detail is not None
    run, attempts, stats = detail
    assert run.title == "detailed"
    assert [(task.node, task.attempt) for task in attempts] == [
        ("build", 1),
        ("build", 2),
        ("review", 1),
    ]
    assert stats.input_tokens == 300
    assert stats.output_tokens == 30
    assert stats.total_tokens == 330
    assert stats.tool_calls == 5
    assert stats.cost == pytest.approx(0.75)
    assert stats.duration_s == pytest.approx(4.0)


async def test_detail_omits_what_nobody_measured(store: Store) -> None:
    """`SUM` over no rows is NULL and stays NULL (01 §Real data only)."""

    run_id = await make_run(store, title="unmeasured")
    await add_task(store, run_id, "build", TaskStatus.done, stats=None)
    await add_task(store, run_id, "review", TaskStatus.done, stats={"input_tokens": 7})

    async with store.reader() as reader:
        detail = await reader.runs.detail(run_id)

    assert detail is not None
    _, _, stats = detail
    assert stats.input_tokens == 7
    assert stats.output_tokens is None
    assert stats.cost is None
    assert stats.duration_s is None
    assert stats.model_dump(exclude_none=True) == {"input_tokens": 7}


async def test_detail_of_a_run_with_no_tasks_has_no_totals(
    store: Store,
) -> None:
    run_id = await make_run(store, title="empty")

    async with store.reader() as reader:
        detail = await reader.runs.detail(run_id)

    assert detail is not None
    _, attempts, stats = detail
    assert attempts == []
    assert stats.model_dump(exclude_none=True) == {}


async def test_detail_of_an_unknown_run_is_none(store: Store) -> None:
    async with store.reader() as reader:
        assert await reader.runs.detail("01JNOSUCHRUN") is None


async def test_detail_tasks_carry_no_token(store: Store) -> None:
    """A task row never serializes its hash (12 §Task tokens)."""

    run_id = await make_run(store, title="tokened")
    task_id = await add_task(store, run_id, "build", TaskStatus.in_progress)
    async with store.uow() as uow:
        await uow.conn.execute(
            tasks.update().where(tasks.c.id == task_id).values(token_hash="a" * 64)
        )

    async with store.reader() as reader:
        detail = await reader.runs.detail(run_id)

    assert detail is not None
    _, attempts, _ = detail
    assert attempts[0].token_hash == "a" * 64
    assert "token_hash" not in attempts[0].model_dump()


# --------------------------------------------------------------------------
# update and set_status
# --------------------------------------------------------------------------


async def test_update_writes_the_fields_and_touches_updated(
    store: Store,
) -> None:
    run_id = await make_run(store, title="before")
    async with store.reader() as reader:
        original = await reader.runs.get(run_id)
    assert original is not None

    async with store.uow() as uow:
        updated = await uow.runs.update(
            run_id, title="after", description="notes", output={"ok": True}
        )

    assert updated is not None
    assert (updated.title, updated.description) == ("after", "notes")
    assert updated.output == {"ok": True}
    assert updated.updated >= original.updated
    assert updated.created == original.created


async def test_update_refuses_a_column_it_does_not_own(store: Store) -> None:
    run_id = await make_run(store)

    async with store.uow() as uow:
        with pytest.raises(ValueError, match="workflow"):
            await uow.runs.update(run_id, workflow="other")


async def test_update_of_an_unknown_run_is_none(store: Store) -> None:
    async with store.uow() as uow:
        assert await uow.runs.update("01JNOSUCHRUN", title="x") is None


async def test_set_status_stamps_finished_only_when_given(
    store: Store,
) -> None:
    run_id = await make_run(store)

    async with store.uow() as uow:
        running = await uow.runs.set_status(run_id, RunStatus.running)
    assert running is not None
    assert running.status is RunStatus.running
    assert running.finished is None

    ended = now()
    async with store.uow() as uow:
        completed = await uow.runs.set_status(
            run_id, RunStatus.completed, finished=ended
        )
    assert completed is not None
    assert completed.status is RunStatus.completed
    assert completed.finished is not None

    async with store.uow() as uow:
        reopened = await uow.runs.update(
            run_id, status=RunStatus.running, finished=None
        )
    assert reopened is not None
    assert reopened.finished is None


async def test_set_status_of_an_unknown_run_is_none(store: Store) -> None:
    async with store.uow() as uow:
        assert await uow.runs.set_status("01JNOSUCHRUN", RunStatus.paused) is None


# --------------------------------------------------------------------------
# Ordering
# --------------------------------------------------------------------------


async def test_swap_position_moves_a_run_up_and_down(store: Store) -> None:
    for title in ("a", "b", "c"):
        await make_run(store, title=title)
    async with store.reader() as reader:
        listed = {run.title: run.id for run in await reader.runs.list()}

    async with store.uow() as uow:
        assert await uow.runs.swap_position(listed["c"], -1) == 2
    assert await positions(store) == [("a", 1), ("c", 2), ("b", 3)]

    async with store.uow() as uow:
        assert await uow.runs.swap_position(listed["c"], 1) == 3
    assert await positions(store) == [("a", 1), ("b", 2), ("c", 3)]


async def test_swap_position_with_no_neighbour_is_a_no_op(store: Store) -> None:
    """At the ends there is nothing to swap with; the position is unchanged."""

    for title in ("a", "b"):
        await make_run(store, title=title)
    async with store.reader() as reader:
        listed = {run.title: run for run in await reader.runs.list()}

    async with store.uow() as uow:
        assert await uow.runs.swap_position(listed["a"].id, -1) == 1
        assert await uow.runs.swap_position(listed["b"].id, 1) == 2

    assert await positions(store) == [("a", 1), ("b", 2)]


async def test_swap_position_of_an_unknown_run_is_none(store: Store) -> None:
    async with store.uow() as uow:
        assert await uow.runs.swap_position("01JNOSUCHRUN", 1) is None


async def test_swap_position_refuses_a_direction_that_is_not_a_step(
    store: Store,
) -> None:
    run_id = await make_run(store)

    async with store.uow() as uow:
        with pytest.raises(ValueError, match="-1 or 1"):
            await uow.runs.swap_position(run_id, 2)


async def test_move_position_to_the_top_renumbers_one_to_n(
    store: Store,
) -> None:
    for title in ("a", "b", "c", "d"):
        await make_run(store, title=title)
    async with store.reader() as reader:
        listed = {run.title: run.id for run in await reader.runs.list()}

    async with store.uow() as uow:
        assert await uow.runs.move_position(listed["d"], 0) == 1

    assert await positions(store) == [("d", 1), ("a", 2), ("b", 3), ("c", 4)]


async def test_move_position_to_the_middle_and_the_end(store: Store) -> None:
    for title in ("a", "b", "c", "d"):
        await make_run(store, title=title)
    async with store.reader() as reader:
        listed = {run.title: run.id for run in await reader.runs.list()}

    async with store.uow() as uow:
        assert await uow.runs.move_position(listed["a"], 2) == 3
    assert await positions(store) == [("b", 1), ("c", 2), ("a", 3), ("d", 4)]

    async with store.uow() as uow:
        assert await uow.runs.move_position(listed["b"], 99) == 4
    assert await positions(store) == [("c", 1), ("a", 2), ("d", 3), ("b", 4)]


async def test_move_position_clamps_a_negative_index(store: Store) -> None:
    for title in ("a", "b"):
        await make_run(store, title=title)
    async with store.reader() as reader:
        listed = {run.title: run.id for run in await reader.runs.list()}

    async with store.uow() as uow:
        assert await uow.runs.move_position(listed["b"], -5) == 1

    assert await positions(store) == [("b", 1), ("a", 2)]


async def test_move_position_is_one_update(store: Store, engine: AsyncEngine) -> None:
    for title in ("a", "b", "c", "d"):
        await make_run(store, title=title)
    async with store.reader() as reader:
        listed = {run.title: run.id for run in await reader.runs.list()}

    async with store.uow() as uow:
        with Counter(engine) as counter:
            await uow.runs.move_position(listed["d"], 0)

    writes = [
        statement
        for statement in counter.statements
        if statement.lstrip().upper().startswith("UPDATE")
    ]
    assert len(writes) == 1
    assert "CASE" in writes[0].upper()


async def test_move_position_of_an_unknown_run_is_none(store: Store) -> None:
    await make_run(store)

    async with store.uow() as uow:
        assert await uow.runs.move_position("01JNOSUCHRUN", 0) is None


async def test_compact_positions_closes_the_gaps(store: Store) -> None:
    for title in ("a", "b", "c", "d"):
        await make_run(store, title=title)
    async with store.reader() as reader:
        listed = {run.title: run.id for run in await reader.runs.list()}
    async with store.uow() as uow:
        await uow.runs.delete(listed["b"])
        await uow.runs.delete(listed["c"])
        await uow.runs.insert("demo", "e")

    async with store.uow() as uow:
        changed = await uow.runs.compact_positions()

    assert changed == 2
    assert await positions(store) == [("a", 1), ("d", 2), ("e", 3)]


async def test_compact_positions_on_a_compact_list_writes_nothing(
    store: Store,
) -> None:
    for title in ("a", "b"):
        await make_run(store, title=title)

    async with store.uow() as uow:
        assert await uow.runs.compact_positions() == 0

    assert await positions(store) == [("a", 1), ("b", 2)]


async def test_compact_positions_breaks_duplicate_positions(store: Store) -> None:
    """Duplicated positions renumber to a permutation, on both backends.

    T018 imports v0's runs with their own ids and maps a priority that can
    tie onto ``position``, so a list with two runs in the same slot is
    reachable — and repairing it is what this method is for. A correlated
    rank subquery inside the ``UPDATE`` gets this wrong on SQLite, which
    sees the rows it has already rewritten within the same statement, and
    right on PostgreSQL, which does not: the larger id is inserted first
    here so the physical order disagrees with the list order, which is
    what exposed the divergence.
    """

    await insert_run_at(store, "Z" * 26, title="z", position=3)
    await insert_run_at(store, "A" * 26, title="a", position=3)

    async with store.uow() as uow:
        changed = await uow.runs.compact_positions()

    listed = await positions(store)
    assert sorted(place for _, place in listed) == [1, 2]
    assert listed == [("a", 1), ("z", 2)]
    assert changed == 2


# --------------------------------------------------------------------------
# delete
# --------------------------------------------------------------------------


async def test_delete_takes_the_whole_run_with_it(store: Store) -> None:
    run_id = await make_run(store, title="doomed")
    task_id = await add_task(store, run_id, "build", TaskStatus.in_progress)
    request_id = await add_request(store, run_id, task_id)
    await answer_request(store, request_id)
    await add_children(store, run_id, task_id)
    await add_event(store, "task.started", run_id, task_id)
    keeper = await make_run(store, title="keeper")
    keeper_task = await add_task(store, keeper, "build", TaskStatus.in_progress)

    async with store.uow() as uow:
        assert await uow.runs.delete(run_id) is True

    assert await count_rows(store, runs, id=run_id) == 0
    assert await count_rows(store, tasks, run_id=run_id) == 0
    assert await count_rows(store, log_entries, run_id=run_id) == 0
    assert await count_rows(store, requests, run_id=run_id) == 0
    assert await count_rows(store, answers, request_id=request_id) == 0
    assert await count_rows(store, events, run_id=run_id) == 0
    # ...and nothing else moved.
    assert await count_rows(store, runs, id=keeper) == 1
    assert await count_rows(store, tasks, id=keeper_task) == 1


async def test_delete_of_an_unknown_run_is_false(store: Store) -> None:
    async with store.uow() as uow:
        assert await uow.runs.delete("01JNOSUCHRUN") is False


async def test_delete_leaves_another_runs_events_alone(store: Store) -> None:
    doomed = await make_run(store, title="doomed")
    keeper = await make_run(store, title="keeper")
    await add_event(store, "run.created", doomed, None)
    await add_event(store, "run.created", keeper, None)

    async with store.uow() as uow:
        await uow.runs.delete(doomed)

    assert await count_rows(store, events, run_id=keeper) == 1


# --------------------------------------------------------------------------
# The dialect switch
# --------------------------------------------------------------------------


DIALECTS = {"sqlite": sqlite.dialect(), "postgresql": postgresql.dialect()}


@pytest.mark.parametrize("name", sorted(DIALECTS))
def test_the_list_query_compiles_for_both_backends(name: str) -> None:
    """The PostgreSQL spelling is checked on a machine with only SQLite.

    A query that only works on one backend would otherwise fail in the
    nightly job rather than in the gate (13 §Pyramid).
    """

    sql = str(
        list_statement(name, status="running", workflow="demo").compile(
            dialect=DIALECTS[name]
        )
    )

    assert sql.count("SELECT") == 3  # the run list and its two subqueries
    assert "ORDER BY runs.position, runs.id" in sql
    assert ("group_concat(DISTINCT" in sql) is (name == "sqlite")
    assert ("string_agg(DISTINCT" in sql) is (name == "postgresql")


@pytest.mark.parametrize("name", sorted(DIALECTS))
def test_the_stats_query_compiles_for_both_backends(name: str) -> None:
    sql = str(stats_statement(name, "01JRUN").compile(dialect=DIALECTS[name]))

    assert sql.count("sum(") == 6
    assert "coalesce" not in sql.lower()  # unknown stays unknown
    assert ("json_extract(tasks.stats" in sql) is (name == "sqlite")
    assert ("jsonb_extract_path_text(tasks.stats" in sql) is (name == "postgresql")


@pytest.mark.parametrize("name", sorted(DIALECTS))
def test_the_aggregates_compile_for_both_backends(name: str) -> None:
    """Both spellings exist even where only one backend is installed."""

    assert current_nodes_expression(name) is not None
    assert stats_value(name, "input_tokens") is not None


@pytest.mark.parametrize(
    "build",
    [current_nodes_expression, lambda name: stats_value(name, "cost")],
)
def test_an_unknown_backend_is_refused_not_guessed(
    build: Any,
) -> None:
    with pytest.raises(NotImplementedError, match="mysql"):
        build("mysql")

"""`JoinRepo`: the upsert, the count, and what "late" means (T024b).

The engine's use of these queries is ``tests/engine/test_fanin.py``'s
subject; what is here is the half that differs by backend. The arrival
insert is an ``ON CONFLICT … DO UPDATE`` and the two dialects build it
from their own ``insert()``, so this file runs on both (13 §Pyramid) —
an upsert that silently became a plain insert on PostgreSQL would count
a retried branch twice and fire a join that is short a deliverable.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy.dialects import postgresql, sqlite

from athanore.store.repos.joins import IncompleteJoin, upsert_statement
from athanore.store.rows import BranchFrame
from athanore.store.uow import Store

WORKFLOW = "demo"
JOIN = "release"


async def make_run(store: Store) -> str:
    async with store.uow() as uow:
        run = await uow.runs.insert(WORKFLOW, "a run")
    return run.id


async def branch(
    store: Store, run_id: str, fanout: int, index: int, count: int, key: Any = None
) -> int:
    """A task carrying one fan-out frame, as a branch of ``fanout`` does."""

    async with store.uow() as uow:
        task = await uow.tasks.enqueue(
            run_id,
            "build",
            key,
            priority=0,
            explicit=False,
            branch=[BranchFrame(fanout=fanout, index=index, count=count, key=key)],
        )
    return task.id


async def arrive(
    store: Store,
    run_id: str,
    *,
    fanout: int,
    index: int,
    count: int,
    key: Any = None,
    value: Any = None,
    from_task: int | None = None,
):
    async with store.uow() as uow:
        return await uow.joins.arrive(
            run_id=run_id,
            join_node=JOIN,
            fanout_task=fanout,
            index=index,
            key=key,
            value=value,
            from_task=from_task,
            count=count,
        )


async def test_arrivals_accumulate_and_report_the_fan_outs_width(
    store: Store,
) -> None:
    run_id = await make_run(store)

    first = await arrive(store, run_id, fanout=7, index=0, count=3, key="d0")
    second = await arrive(store, run_id, fanout=7, index=1, count=3, key="d1")

    assert (first.arrived, first.count, first.late) == (1, 3, False)
    assert (second.arrived, second.count, second.late) == (2, 3, False)


async def test_the_same_index_arriving_twice_replaces_its_value(store: Store) -> None:
    run_id = await make_run(store)

    await arrive(store, run_id, fanout=7, index=0, count=2, key="d0", value="first")
    again = await arrive(
        store, run_id, fanout=7, index=0, count=2, key="d0", value="second"
    )

    assert again.arrived == 1
    async with store.reader() as reader:
        rows = await reader.joins.arrivals(run_id, JOIN, 7)
    assert [(row.index, row.value) for row in rows] == [(0, "second")]


async def test_arrivals_come_back_in_index_order(store: Store) -> None:
    run_id = await make_run(store)

    for index in (2, 0, 1):
        await arrive(store, run_id, fanout=7, index=index, count=3, key=f"d{index}")

    async with store.reader() as reader:
        rows = await reader.joins.arrivals(run_id, JOIN, 7)
    assert [row.index for row in rows] == [0, 1, 2]
    assert [row.key for row in rows] == ["d0", "d1", "d2"]


async def test_arrivals_of_another_fan_out_are_not_counted(store: Store) -> None:
    run_id = await make_run(store)

    await arrive(store, run_id, fanout=7, index=0, count=2)
    other = await arrive(store, run_id, fanout=9, index=0, count=2)

    assert other.arrived == 1


async def test_an_arrival_is_late_once_the_join_task_exists(store: Store) -> None:
    run_id = await make_run(store)
    await arrive(store, run_id, fanout=7, index=0, count=2)
    async with store.uow() as uow:
        await uow.tasks.enqueue(
            run_id,
            JOIN,
            [],
            priority=0,
            explicit=False,
            lineage={"from": 7, "reason": "join", "arrivals": []},
        )

    late = await arrive(store, run_id, fanout=7, index=1, count=2)

    assert late.late is True
    async with store.reader() as reader:
        rows = await reader.joins.arrivals(run_id, JOIN, 7)
    assert [row.late for row in rows] == [False, True]


async def test_a_join_task_of_another_fan_out_does_not_make_arrivals_late(
    store: Store,
) -> None:
    run_id = await make_run(store)
    async with store.uow() as uow:
        await uow.tasks.enqueue(
            run_id,
            JOIN,
            [],
            priority=0,
            explicit=False,
            lineage={"from": 9, "reason": "join", "arrivals": []},
        )

    arrival = await arrive(store, run_id, fanout=7, index=0, count=2)

    assert arrival.late is False


async def test_incomplete_names_the_fan_outs_short_of_their_branches(
    store: Store,
) -> None:
    run_id = await make_run(store)
    tasks = [
        await branch(store, run_id, 7, index, 3, f"d{index}") for index in range(3)
    ]
    await arrive(store, run_id, fanout=7, index=0, count=3, from_task=tasks[0])
    await arrive(store, run_id, fanout=7, index=1, count=3, from_task=tasks[1])

    async with store.reader() as reader:
        partial = await reader.joins.incomplete(run_id)

    assert partial == [
        IncompleteJoin(join_node=JOIN, fanout_task=7, arrived=2, count=3)
    ]


async def test_a_fan_out_that_all_arrived_is_not_incomplete(store: Store) -> None:
    run_id = await make_run(store)
    for index in range(2):
        await branch(store, run_id, 7, index, 2)
        await arrive(store, run_id, fanout=7, index=index, count=2)

    async with store.reader() as reader:
        assert await reader.joins.incomplete(run_id) == []


async def test_a_run_with_no_arrivals_has_nothing_incomplete(store: Store) -> None:
    run_id = await make_run(store)
    await branch(store, run_id, 7, 0, 2)

    async with store.reader() as reader:
        assert await reader.joins.incomplete(run_id) == []


async def test_another_runs_arrivals_are_not_reported(store: Store) -> None:
    mine = await make_run(store)
    theirs = await make_run(store)
    await branch(store, theirs, 7, 0, 2)
    await arrive(store, theirs, fanout=7, index=0, count=2)

    async with store.reader() as reader:
        assert await reader.joins.incomplete(mine) == []
        assert len(await reader.joins.incomplete(theirs)) == 1


# --------------------------------------------------------------------------
# The dialect switch
# --------------------------------------------------------------------------


DIALECTS = {"sqlite": sqlite.dialect(), "postgresql": postgresql.dialect()}

VALUES: dict[str, Any] = {
    "run_id": "01JRUN",
    "join_node": JOIN,
    "fanout_task": 7,
    "index": 0,
    "key": "d0",
    "value": None,
    "from_task": 11,
    "late": False,
    "created": datetime(2026, 9, 6, tzinfo=UTC),
}


@pytest.mark.parametrize("name", sorted(DIALECTS))
def test_the_arrival_upsert_compiles_for_both_backends(name: str) -> None:
    """The PostgreSQL spelling is checked on a machine with only SQLite.

    The conflict target is the unique key of ``join_arrivals``, and the
    updated columns are everything but that key: an upsert that lost
    either would count a retried branch twice (13 §Pyramid).
    """

    # SQLite quotes `index` and `key`, PostgreSQL does not; the shape is
    # what this asserts, so the quotes are dropped first.
    sql = str(upsert_statement(name, VALUES).compile(dialect=DIALECTS[name]))
    sql = sql.replace('"', "")

    assert "INSERT INTO join_arrivals" in sql
    assert "ON CONFLICT (run_id, join_node, fanout_task, index) DO UPDATE" in sql
    for column in ("key", "value", "from_task", "late", "created"):
        assert f"{column} = excluded.{column}" in sql
    assert "index = excluded" not in sql


def test_an_unknown_backend_is_refused_not_guessed() -> None:
    with pytest.raises(NotImplementedError, match="mysql"):
        upsert_statement("mysql", VALUES)

"""The join repository: which branches of a fan-out have arrived (04 §Fan-in).

A fan-out of N branches ends at a join node only when all N have
transitioned into it, and "all N" has to survive a restart — so an
arrival is a row, not a counter in memory. This module owns that table
and the three questions the engine asks of it: record an arrival and say
how many there now are (:meth:`JoinRepo.arrive`), read them back in
fan-out order to build the join task's payload (:meth:`JoinRepo.arrivals`),
and name the fan-outs that will never complete (:meth:`JoinRepo.incomplete`).

Three things are worth stating once, here:

- **The insert is an upsert.** ``(run_id, join_node, fanout_task, index)``
  is unique (07 §Schema), so a branch that arrives twice — a retried
  branch, a re-executed attempt after a crash — is stored once. Before
  the join fires the second arrival replaces the first's value; after it,
  the row is marked ``late`` and the join does not fire again (04
  §Failure and operator semantics). Nothing is dropped silently, and
  nothing is counted twice.

- **"The join already fired" is a fact about ``tasks``.** A join task
  carries ``lineage = {"from": <fanout>, "reason": "join"}``, which is the
  only durable record that a given fan-out has been dispatched. So
  :meth:`JoinRepo.arrive` reads it there rather than keeping a flag of its
  own that a rerun could then contradict.

- **The expected ``count`` lives on the branch frames.** ``join_arrivals``
  has no ``count`` column, and it does not need one: a fan-out of N
  pushes ``{fanout, index, count: N, key}`` onto each child, so every
  task of that branch carries the count (04 §Branch frames).
  :meth:`JoinRepo.arrive` therefore takes it from the caller, which
  popped the frame, and :meth:`JoinRepo.incomplete` recovers it from the
  task rows (D102).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, cast

from sqlalchemy import Insert, func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from athanore.store.clock import now
from athanore.store.repos.base import (
    POSTGRESQL,
    SQLITE,
    Repo,
    unsupported_dialect,
)
from athanore.store.rows import ArrivalRow
from athanore.store.tables import join_arrivals, tasks

#: The columns that identify one branch's arrival: the unique key of
#: ``join_arrivals`` and the conflict target of the upsert.
KEY: tuple[str, ...] = ("run_id", "join_node", "fanout_task", "index")

#: The ``lineage.reason`` a join task carries, and the key its fan-out is
#: recorded under (04 §Arrival and dispatch).
JOIN_REASON: Final = "join"
LINEAGE_FROM: Final = "from"
LINEAGE_REASON: Final = "reason"


@dataclass(frozen=True, slots=True)
class Arrival:
    """What :meth:`JoinRepo.arrive` answers: where the fan-out now stands.

    ``arrived == count`` and ``not late`` is the one combination that
    dispatches the join, and the caller does that in the same transaction
    (04 §Arrival and dispatch).

    A frozen dataclass rather than the ``NamedTuple`` the rest of the
    store returns: ``count`` is a method of ``tuple``, and a field that
    shadows one is a type error before it is a readability problem.
    """

    arrived: int
    count: int
    late: bool


@dataclass(frozen=True, slots=True)
class IncompleteJoin:
    """A fan-out that has arrivals, but not all of them.

    At quiescence this is a deadlock rather than a completion, and the
    runner fails the run with ``join_incomplete`` (03 invariant 4).
    """

    join_node: str
    fanout_task: int
    arrived: int
    count: int


def upsert_statement(dialect: str, values: dict[str, Any]) -> Insert:
    """The arrival insert for ``dialect``, replacing an earlier arrival.

    Both backends spell ``ON CONFLICT … DO UPDATE`` the same way through
    their own ``insert()``; only the constructor differs, so the
    statement is built once and the dialect picks the builder. The
    updated columns are everything but the key: an arrival that replaces
    another carries its own value, its own sender and its own timestamp.
    """

    if dialect == SQLITE:
        statement = sqlite_insert(join_arrivals).values(**values)
    elif dialect == POSTGRESQL:
        statement = postgresql_insert(join_arrivals).values(**values)
    else:
        raise unsupported_dialect(dialect, "JoinRepo.arrive")
    return statement.on_conflict_do_update(
        index_elements=[join_arrivals.c[column] for column in KEY],
        set_={
            "key": statement.excluded.key,
            "value": statement.excluded.value,
            "from_task": statement.excluded.from_task,
            "late": statement.excluded.late,
            "created": statement.excluded.created,
        },
    )


class JoinRepo(Repo):
    """Queries over ``join_arrivals`` (07 §Schema)."""

    async def arrive(
        self,
        run_id: str,
        join_node: str,
        fanout_task: int,
        index: int,
        key: Any,
        value: Any,
        from_task: int | None,
        count: int,
    ) -> Arrival:
        """Record one branch reaching ``join_node``; report where that leaves it.

        ``count`` is the fan-out's width, read by the caller from the
        frame it popped: the table stores no such column, and a fan-out
        that transitions straight into a join leaves no task row carrying
        the frame, so the store cannot always recover it (D102).

        ``late`` is decided before the insert and stored with it: it is
        ``True`` when the join task for this fan-out already exists, in
        which case the arrival is history rather than an input, and the
        caller must not dispatch a second join task.
        """

        late = await self.fired(run_id, join_node, fanout_task)
        await self.conn.execute(
            upsert_statement(
                self.dialect,
                {
                    "run_id": run_id,
                    "join_node": join_node,
                    "fanout_task": fanout_task,
                    "index": index,
                    "key": key,
                    "value": value,
                    "from_task": from_task,
                    "late": late,
                    "created": now(),
                },
            )
        )
        arrived = await self._arrived(run_id, join_node, fanout_task)
        return Arrival(arrived=arrived, count=count, late=late)

    async def arrivals(
        self, run_id: str, join_node: str, fanout_task: int
    ) -> list[ArrivalRow]:
        """Every arrival of one fan-out at one join, in fan-out order.

        Ordered by ``index``, never by arrival time: the join's payload is
        the branches in the order the fan-out produced them, so a run's
        output does not depend on which branch happened to finish first
        (04 §Arrival and dispatch, D58).
        """

        result = await self.conn.execute(
            select(join_arrivals)
            .where(
                join_arrivals.c.run_id == run_id,
                join_arrivals.c.join_node == join_node,
                join_arrivals.c.fanout_task == fanout_task,
            )
            .order_by(join_arrivals.c["index"])
        )
        return self._rows(ArrivalRow, result)

    async def incomplete(self, run_id: str) -> list[IncompleteJoin]:
        """The run's fan-outs that have arrivals but not all of them.

        The question the runner asks when a run falls quiet: no pending
        tasks and a partial join is a deadlock, and 03 invariant 4 says it
        is ``failed`` rather than ``completed``.

        A fan-out whose width no task row carries is skipped rather than
        reported. That is only ever a fan-out which transitioned straight
        into the join — every one of its arrivals is written in the
        transaction that created them, so it fired then or never had a
        branch outstanding (D102).
        """

        result = await self.conn.execute(
            select(
                join_arrivals.c.join_node,
                join_arrivals.c.fanout_task,
                func.count().label("arrived"),
            )
            .where(join_arrivals.c.run_id == run_id)
            .group_by(join_arrivals.c.join_node, join_arrivals.c.fanout_task)
            .order_by(join_arrivals.c.join_node, join_arrivals.c.fanout_task)
        )
        rows = [
            (str(row.join_node), int(row.fanout_task), int(row.arrived))
            for row in result
        ]
        if not rows:
            return []
        widths = await self._fanout_widths(run_id)
        partial: list[IncompleteJoin] = []
        for join_node, fanout_task, arrived in rows:
            count = widths.get(fanout_task)
            if count is None or arrived >= count:
                continue
            partial.append(
                IncompleteJoin(
                    join_node=join_node,
                    fanout_task=fanout_task,
                    arrived=arrived,
                    count=count,
                )
            )
        return partial

    async def fired(self, run_id: str, join_node: str, fanout_task: int) -> bool:
        """Whether ``fanout_task``'s join task has already been enqueued.

        Read from the lineage of the tasks at ``join_node``, because that
        is where the dispatch is recorded (04 §Arrival and dispatch). The
        filter is by run and node — a handful of rows — and the lineage is
        matched in Python: a JSON member's spelling differs between the
        two backends, and this question is not worth a dialect switch.
        """

        result = await self.conn.execute(
            select(tasks.c.lineage).where(
                tasks.c.run_id == run_id, tasks.c.node == join_node
            )
        )
        for (lineage,) in result:
            if not isinstance(lineage, dict):
                continue
            entry = cast("dict[str, Any]", lineage)
            if (
                entry.get(LINEAGE_REASON) == JOIN_REASON
                and entry.get(LINEAGE_FROM) == fanout_task
            ):
                return True
        return False

    async def _arrived(self, run_id: str, join_node: str, fanout_task: int) -> int:
        """How many distinct branches of this fan-out have arrived."""

        result = await self.conn.execute(
            select(func.count())
            .select_from(join_arrivals)
            .where(
                join_arrivals.c.run_id == run_id,
                join_arrivals.c.join_node == join_node,
                join_arrivals.c.fanout_task == fanout_task,
            )
        )
        return int(result.scalar_one())

    async def _fanout_widths(self, run_id: str) -> dict[int, int]:
        """Every fan-out of the run and how many branches it made.

        Read off the branch frames of the run's tasks: a fan-out of N
        pushes ``count: N`` onto each child, so any task of any of those
        branches answers for it (04 §Branch frames).
        """

        result = await self.conn.execute(
            select(tasks.c.branch).where(tasks.c.run_id == run_id)
        )
        widths: dict[int, int] = {}
        for (branch,) in result:
            if not isinstance(branch, list):
                continue
            for frame in cast("list[Any]", branch):
                if not isinstance(frame, dict):
                    continue
                entry = cast("dict[str, Any]", frame)
                fanout, count = entry.get("fanout"), entry.get("count")
                if isinstance(fanout, int) and isinstance(count, int):
                    widths[fanout] = count
        return widths


__all__ = [
    "JOIN_REASON",
    "KEY",
    "LINEAGE_FROM",
    "LINEAGE_REASON",
    "Arrival",
    "IncompleteJoin",
    "JoinRepo",
    "upsert_statement",
]

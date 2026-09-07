"""The run repository: the list, the detail, the order, and the delete.

07 §Schema owns the columns and 03 §Run owns their meaning; this module
is where the two queries that are not a plain ``SELECT *`` live:

- :meth:`RunRepo.list` returns a :class:`~athanore.store.rows.RunSummary`
  per run, with ``current_nodes`` and ``pending_requests`` as two
  correlated scalar subqueries inside **one** statement. 07
  §Repositories is explicit that these are never a per-run loop: the run
  list is the SPA's home screen and refreshes on every ``run.*`` event.
- :meth:`RunRepo.detail` totals the per-attempt ``tasks.stats`` entries
  (05 §Stats entry) with ``SUM`` over the JSON values, so a run's totals
  are one aggregate rather than an event scan.

Both aggregates are dialect-switched — ``GROUP_CONCAT`` against
``string_agg``, ``json_extract`` against ``jsonb_extract_path_text`` —
and both statements are built by module-level functions that take a
dialect *name*: :func:`list_statement` and :func:`stats_statement`. That
is what lets the suite compile the PostgreSQL spelling on a machine with
only SQLite installed, so a query that only works on one backend fails in
the gate rather than in the nightly job.

**Ordering.** The list order is ``position ASC`` (03 §Identifiers and
ordering) with ``id`` as the tiebreaker, and it is the only order this
module knows: what *uses* it to dispatch is the scheduler's business.
New runs append at ``max(position) + 1``, a reorder is a swap with a
neighbour or a move to a zero-based index, and positions are compacted
lazily by :meth:`RunRepo.compact_positions`.

**Honesty.** ``SUM`` over no rows is ``NULL`` and stays ``NULL``:
:class:`~athanore.store.rows.RunStats` omits what nobody measured rather
than reporting zero (01 §Real data only). Nothing here coalesces a total.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    ColumnElement,
    Numeric,
    Select,
    and_,
    case,
    cast,
    func,
    literal_column,
    or_,
    select,
)
from ulid import ULID

from athanore.store.clock import now
from athanore.store.repos.base import (
    POSTGRESQL,
    SQLITE,
    Repo,
    unsupported_dialect,
)
from athanore.store.rows import (
    RunRow,
    RunStats,
    RunStatus,
    RunSummary,
    TaskRow,
    TaskStatus,
)
from athanore.store.tables import answers, events, requests, runs, tasks

#: The task statuses that make a run's node "current" and its requests
#: answerable: a body is running or parked in ``human_input`` (03).
IN_FLIGHT: tuple[str, str] = (TaskStatus.in_progress.value, TaskStatus.waiting.value)

#: The separator both backends aggregate ``current_nodes`` with. Node
#: names are Python identifiers, so no name can contain it.
NODE_SEPARATOR = ","

#: The columns :meth:`RunRepo.update` accepts. ``id``, ``workflow`` and
#: ``created`` are not among them: a run's identity and its workflow never
#: change (invariant 3 of 03), and ``updated`` is this repository's to
#: write, never the caller's.
UPDATABLE: frozenset[str] = frozenset(
    {"title", "description", "status", "output", "position", "finished"}
)

#: The stats keys of 05 §Stats entry that total across a run, and whether
#: each is a count or a measure. The other keys of the entry — ``model``,
#: ``session_id``, ``reason`` — are per attempt and do not sum.
_STATS_INT: tuple[str, ...] = (
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "tool_calls",
)
_STATS_FLOAT: tuple[str, ...] = ("cost", "duration_s")


def current_nodes_expression(dialect: str) -> ColumnElement[str | None]:
    """The aggregate of the distinct in-flight node names, for ``dialect``.

    SQLite's ``group_concat`` takes no separator argument alongside
    ``DISTINCT``; its default is a comma, which is what PostgreSQL is
    asked for explicitly so the two produce the same string.
    """

    if dialect == SQLITE:
        return func.group_concat(tasks.c.node.distinct())
    if dialect == POSTGRESQL:
        return func.string_agg(
            tasks.c.node.distinct(), literal_column(f"'{NODE_SEPARATOR}'")
        )
    raise unsupported_dialect(dialect, "current_nodes")


def stats_value(dialect: str, key: str) -> ColumnElement[Any]:
    """One value of ``tasks.stats``, typed so ``SUM`` can add it up.

    SQLite's ``json_extract`` hands back the JSON value with its own type.
    PostgreSQL's ``jsonb_extract_path_text`` hands back text, so it is
    cast to ``NUMERIC`` — which accepts both ``12406`` and ``0.0123`` and
    is what makes one expression serve a token count and a cost.
    """

    if dialect == SQLITE:
        return func.json_extract(tasks.c.stats, f"$.{key}")
    if dialect == POSTGRESQL:
        return cast(func.jsonb_extract_path_text(tasks.c.stats, key), Numeric)
    raise unsupported_dialect(dialect, "tasks.stats extraction")


def list_statement(
    dialect: str, status: str | None = None, workflow: str | None = None
) -> Select[Any]:
    """The run list of 08 §Runs: every column plus the two aggregates.

    One statement. ``current_nodes`` and ``pending_requests`` are
    correlated scalar subqueries, never a second round trip per run
    (07 §Repositories).
    """

    in_flight_nodes = (
        select(current_nodes_expression(dialect))
        .select_from(tasks)
        .where(tasks.c.run_id == runs.c.id, tasks.c.status.in_(IN_FLIGHT))
        .correlate(runs)
        .scalar_subquery()
    )
    open_requests = (
        select(func.count())
        .select_from(
            requests.join(tasks, tasks.c.id == requests.c.task_id).outerjoin(
                answers, answers.c.request_id == requests.c.id
            )
        )
        .where(
            requests.c.run_id == runs.c.id,
            answers.c.request_id.is_(None),
            tasks.c.status.in_(IN_FLIGHT),
        )
        .correlate(runs)
        .scalar_subquery()
    )
    statement = select(
        *runs.c,
        in_flight_nodes.label("current_nodes"),
        open_requests.label("pending_requests"),
    )
    if status is not None:
        statement = statement.where(runs.c.status == str(status))
    if workflow is not None:
        statement = statement.where(runs.c.workflow == workflow)
    return statement.order_by(runs.c.position, runs.c.id)


def stats_statement(dialect: str, run_id: str) -> Select[Any]:
    """The totals of a run's per-attempt ``tasks.stats`` entries.

    Every attempt, failed ones included: the tokens a dead-lettered
    attempt spent were still spent. Nothing is coalesced — ``SUM`` over no
    rows is ``NULL``, and ``NULL`` is how
    :class:`~athanore.store.rows.RunStats` says "nobody measured this".
    """

    return select(
        *(
            func.sum(stats_value(dialect, key)).label(key)
            for key in (*_STATS_INT, *_STATS_FLOAT)
        )
    ).where(tasks.c.run_id == run_id)


def _as_int(value: Any) -> int | None:
    """A summed count, or ``None`` when no attempt reported one."""

    return None if value is None else int(value)


def _as_float(value: Any) -> float | None:
    """A summed measure, or ``None`` when no attempt reported one."""

    return None if value is None else float(value)


class RunRepo(Repo):
    """Queries over ``runs`` (07 §Schema)."""

    async def insert(self, workflow: str, title: str, description: str = "") -> RunRow:
        """Create a queued run at the bottom of the list.

        ``position`` is ``COALESCE(MAX(position), 0) + 1`` computed inside
        the insert, so two runs created in the same transaction cannot be
        handed the same slot by a read that raced the write.
        """

        stamp = now()
        next_position = (
            select(func.coalesce(func.max(runs.c.position), 0) + 1)
            .select_from(runs)
            .scalar_subquery()
        )
        result = await self.conn.execute(
            runs.insert()
            .values(
                id=str(ULID()),
                workflow=workflow,
                title=title,
                description=description,
                status=RunStatus.queued.value,
                output=None,
                position=next_position,
                created=stamp,
                updated=stamp,
                finished=None,
            )
            .returning(*runs.c)
        )
        row = self._first(RunRow, result)
        if row is None:  # pragma: no cover - an INSERT ... RETURNING has a row
            raise RuntimeError("the run insert returned no row")
        return row

    async def get(self, run_id: str) -> RunRow | None:
        """One run, or ``None``."""

        result = await self.conn.execute(select(runs).where(runs.c.id == run_id))
        return self._first(RunRow, result)

    async def count_running(self) -> int:
        """How many runs are ``running`` — ``/api/health``'s ``runs_running``.

        A count, never a list: the health endpoint reports no ids
        (08 §System), and a server with thousands of runs must not
        serialise any of them to answer a poll.
        """

        result = await self.conn.execute(
            select(func.count())
            .select_from(runs)
            .where(runs.c.status == RunStatus.running.value)
        )
        return int(result.scalar_one())

    async def list(
        self, status: str | None = None, workflow: str | None = None
    ) -> list[RunSummary]:
        """Every run in list order, with its two derived fields.

        One statement: the aggregates are correlated scalar subqueries, not
        a second round trip per run (07 §Repositories). ``unregistered`` is
        not stored and is left ``False`` here — whether this server has the
        workflow is the registry's question, a tier up (03 §Run).
        """

        result = await self.conn.execute(list_statement(self.dialect, status, workflow))
        summaries: list[RunSummary] = []
        for mapping in result.mappings():
            fields = dict(mapping)
            fields["current_nodes"] = _split_nodes(fields["current_nodes"])
            fields["pending_requests"] = int(fields["pending_requests"] or 0)
            summaries.append(self._row(RunSummary, fields))
        return summaries

    async def detail(
        self, run_id: str
    ) -> tuple[RunRow, list[TaskRow], RunStats] | None:
        """The run, its every task attempt, and the totals of their stats.

        The totals span **every** attempt, failed ones included: the tokens
        a dead-lettered attempt spent were still spent (05 §Stats entry).
        """

        run = await self.get(run_id)
        if run is None:
            return None

        result = await self.conn.execute(
            select(tasks).where(tasks.c.run_id == run_id).order_by(tasks.c.id)
        )
        attempts = self._rows(TaskRow, result)

        keys = (*_STATS_INT, *_STATS_FLOAT)
        totals = await self.conn.execute(
            select(
                *(func.sum(stats_value(self.dialect, key)).label(key) for key in keys)
            ).where(tasks.c.run_id == run_id)
        )
        summed = totals.mappings().one()
        stats = RunStats.model_validate(
            {key: _as_int(summed[key]) for key in _STATS_INT}
            | {key: _as_float(summed[key]) for key in _STATS_FLOAT}
        )
        return run, attempts, stats

    async def update(self, run_id: str, **fields: Any) -> RunRow | None:
        """Write ``fields`` and touch ``updated``; ``None`` if there is no run.

        Only the columns of :data:`UPDATABLE` are accepted. An unknown one
        is a programming error and raises rather than being dropped: a
        silently ignored field is an operator edit that appears to have
        worked.
        """

        unknown = sorted(set(fields) - UPDATABLE)
        if unknown:
            raise ValueError(
                f"runs has no updatable column {unknown}; "
                f"updatable columns are {sorted(UPDATABLE)}"
            )
        values: dict[str, Any] = dict(fields)
        if "status" in values:
            values["status"] = str(values["status"])
        values["updated"] = now()
        result = await self.conn.execute(
            runs.update().where(runs.c.id == run_id).values(**values).returning(*runs.c)
        )
        return self._first(RunRow, result)

    async def set_status(
        self, run_id: str, status: str, finished: datetime | None = None
    ) -> RunRow | None:
        """Move a run to ``status``, stamping ``finished`` when one is given.

        ``finished=None`` leaves the column alone, so re-opening a finished
        run by retry or rerun clears it through
        ``update(run_id, finished=None)`` — explicitly, where the caller
        can see it.
        """

        values: dict[str, Any] = {"status": str(status), "updated": now()}
        if finished is not None:
            values["finished"] = finished
        result = await self.conn.execute(
            runs.update().where(runs.c.id == run_id).values(**values).returning(*runs.c)
        )
        return self._first(RunRow, result)

    async def swap_position(self, run_id: str, direction: int) -> int | None:
        """Swap a run with the neighbour above (-1) or below (+1).

        Returns the run's position afterwards, or ``None`` if there is no
        such run. At either end there is no neighbour and nothing moves:
        the call is a no-op and returns the position it already had (08
        §Runs — still 200, with the current position).
        """

        if direction not in (-1, 1):
            raise ValueError(f"direction must be -1 or 1, not {direction!r}")
        row = await self.get(run_id)
        if row is None:
            return None

        before = or_(
            runs.c.position < row.position,
            and_(runs.c.position == row.position, runs.c.id < row.id),
        )
        after = or_(
            runs.c.position > row.position,
            and_(runs.c.position == row.position, runs.c.id > row.id),
        )
        if direction < 0:
            neighbour_query = (
                select(runs.c.id, runs.c.position)
                .where(before)
                .order_by(runs.c.position.desc(), runs.c.id.desc())
            )
        else:
            neighbour_query = (
                select(runs.c.id, runs.c.position)
                .where(after)
                .order_by(runs.c.position, runs.c.id)
            )
        neighbour = (await self.conn.execute(neighbour_query.limit(1))).first()
        if neighbour is None:
            return row.position

        await self.conn.execute(
            runs.update().where(runs.c.id == run_id).values(position=neighbour.position)
        )
        await self.conn.execute(
            runs.update().where(runs.c.id == neighbour.id).values(position=row.position)
        )
        return int(neighbour.position)

    async def move_position(self, run_id: str, index: int) -> int | None:
        """Move a run to the zero-based list ``index`` and renumber 1..n.

        ``index`` is clamped to ``[0, count - 1]`` (08 §Runs). The
        renumbering is one ``UPDATE … CASE`` over the runs whose position
        actually changes, not a statement per run.
        """

        ordered = list(
            (
                await self.conn.execute(
                    select(runs.c.id, runs.c.position).order_by(
                        runs.c.position, runs.c.id
                    )
                )
            ).all()
        )
        ids = [str(row.id) for row in ordered]
        if run_id not in ids:
            return None
        current = {str(row.id): int(row.position) for row in ordered}

        ids.remove(run_id)
        target = max(0, min(index, len(ids)))
        ids.insert(target, run_id)
        renumbered = {run: place for place, run in enumerate(ids, start=1)}
        await self._renumber(renumbered, current)
        return renumbered[run_id]

    async def compact_positions(self) -> int:
        """Renumber every run 1..n in list order; return the rows changed.

        The rank is computed in Python and written as one
        ``UPDATE … CASE``, exactly as :meth:`move_position` does. A
        correlated rank subquery inside the ``UPDATE`` would be wrong on
        SQLite, which evaluates the subquery against the rows it has
        already rewritten within the same statement: two runs sharing a
        position could both be assigned the same rank, while PostgreSQL's
        statement snapshot would give a different — correct — answer. The
        duplicate positions that expose the divergence are precisely the
        state this method exists to repair (T018 maps v0's tieable
        priorities onto ``position``), so the renumbering must not depend
        on the list already being a permutation.

        Runs whose position is already right are excluded from the
        statement, so compacting an already-compact list writes nothing.
        """

        ordered = list(
            (
                await self.conn.execute(
                    select(runs.c.id, runs.c.position).order_by(
                        runs.c.position, runs.c.id
                    )
                )
            ).all()
        )
        current = {str(row.id): int(row.position) for row in ordered}
        renumbered = {str(row.id): place for place, row in enumerate(ordered, start=1)}
        return await self._renumber(renumbered, current)

    async def delete(self, run_id: str) -> bool:
        """Delete a run and everything under it; ``False`` if there was none.

        One ``DELETE``: every foreign key in the schema cascades, so the
        tasks, log entries, submissions, stream chunks, requests, answers
        and join arrivals go with it (07 §Schema notes). ``events`` is the
        one table with no key — the outbox inserts ``run.deleted`` when
        this transaction commits, and a cascade would refuse it on the way
        in (D83) — so its rows are swept by a second statement here.
        """

        result = await self.conn.execute(runs.delete().where(runs.c.id == run_id))
        if result.rowcount == 0:
            return False
        await self.conn.execute(events.delete().where(events.c.run_id == run_id))
        return True

    async def _renumber(
        self, renumbered: dict[str, int], current: dict[str, int]
    ) -> int:
        """Write ``renumbered`` in one ``UPDATE … CASE``; return rows changed.

        Rows already carrying their new position are left out of the
        statement, so a renumbering that moves nothing sends no SQL.
        """

        changed = {
            run: place for run, place in renumbered.items() if current.get(run) != place
        }
        if not changed:
            return 0
        await self.conn.execute(
            runs.update()
            .where(runs.c.id.in_(list(changed)))
            .values(position=case(changed, value=runs.c.id))
        )
        return len(changed)


def _split_nodes(aggregated: object) -> list[str]:
    """The aggregated ``current_nodes`` string as a sorted list of names.

    Sorted rather than left in the backend's aggregation order, which
    neither dialect defines without an ``ORDER BY`` inside the aggregate.
    """

    if aggregated is None:
        return []
    return sorted({name for name in str(aggregated).split(NODE_SEPARATOR) if name})


__all__ = [
    "IN_FLIGHT",
    "NODE_SEPARATOR",
    "UPDATABLE",
    "RunRepo",
    "current_nodes_expression",
    "list_statement",
    "stats_statement",
    "stats_value",
]

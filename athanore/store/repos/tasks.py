"""The task repository: one attempt of one node, and the claim that starts it.

A row of ``tasks`` is one *attempt* (03 §Task): a retry is a new row, not
a mutation of the old one, so nothing here overwrites history. What the
module does own is every transition an attempt makes — enqueued, claimed,
finished — plus the two queries the engine asks about a run as a whole
(:meth:`TaskRepo.has_pending`, :meth:`TaskRepo.terminal_tasks`) and the
one it asks at startup (:meth:`TaskRepo.reset_for_recovery`).

Four things are worth stating once, here:

- **The engine owns the clock.** ``created`` is a parameter of
  :meth:`TaskRepo.enqueue`, not a default on the column, because a retry
  carries the failed attempt's ``created`` forward (03, 04 §Running an
  attempt). That is what stops a flapping node from jumping the queue
  every time it fails: the dispatch order's last tiebreaker is
  ``created DESC``, so a retry that minted a fresh timestamp would
  overtake everything enqueued while it was running.

- **The claim is the concurrency.** :meth:`TaskRepo.claim_ready` is the
  one query in the store with more than one writer in mind. Its ordering
  is 04 §Dispatch order verbatim — run position dominates, then explicit
  priorities, then downstream-first, then newest-first — and it is
  transcribed, never re-derived. On PostgreSQL the select takes
  ``FOR UPDATE OF tasks SKIP LOCKED``; on SQLite the single writer makes
  it atomic (07 §Repositories). Either way the ``UPDATE`` re-checks
  ``status = 'ready'``, so a row another claimer won is skipped rather
  than claimed twice.

- **A token exists only for a claimed attempt** (D38, 12 §Task tokens).
  It is minted here, its SHA-256 is stored, and the clear text is
  returned once with the claimed row and never written anywhere. A
  recovered or retried attempt is a different attempt and gets a
  different token, which is why :meth:`TaskRepo.reset_for_recovery`
  clears ``token_hash``: a token captured from an attempt that died is
  dead with it.

- **Branch order is a path, not a column.** A terminal task's place in a
  fan-out is the tuple of its frame indexes, outermost first (04 §Routing
  edge cases), and no index on a JSON array expresses that on both
  backends. :meth:`TaskRepo.terminal_tasks` therefore selects the rows
  and orders them in Python, on the frames the read model already parsed.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Sequence
from datetime import datetime
from typing import Any, NamedTuple

from sqlalchemy import Select, case, select

from athanore.store.clock import now
from athanore.store.repos.base import (
    POSTGRESQL,
    SQLITE,
    Repo,
    unsupported_dialect,
)
from athanore.store.rows import BranchFrame, RunStatus, TaskRow, TaskStatus
from athanore.store.tables import runs, tasks

#: The task statuses that mean a run still has work outstanding: queued
#: for a slot, running, or parked in ``human_input`` (03 §Task).
PENDING: tuple[str, str, str] = (
    TaskStatus.ready.value,
    TaskStatus.in_progress.value,
    TaskStatus.waiting.value,
)

#: The statuses a crash or a shutdown can leave behind. Neither is a
#: decision anybody made, so recovery returns both to ``ready``
#: (04 §Recovery on startup, §Shutdown).
INTERRUPTED: tuple[str, str] = (
    TaskStatus.in_progress.value,
    TaskStatus.waiting.value,
)

#: The run statuses a task may be claimed under. ``paused`` is absent by
#: design: pausing a run is how an operator stops it dispatching, and the
#: in-flight attempts finish while nothing new starts (04 §Operator
#: operations).
CLAIMABLE_RUNS: tuple[str, str] = (RunStatus.queued.value, RunStatus.running.value)

#: The number of random bytes a task token carries before base64url
#: encoding (12 §Task tokens; ``secrets.token_urlsafe``).
TOKEN_BYTES = 32


class ClaimedTask(NamedTuple):
    """One task the scheduler just took, with the token minted for it.

    ``token`` is clear text and lives only in the runner's memory from
    here (04 §Dispatch order); the store keeps its SHA-256 and nothing
    else. ``run_started`` is ``True`` on exactly one claimed task per run
    this claim moved ``queued → running``, so ``run.started`` is emitted
    once however many of that run's tasks were claimed together.
    """

    task: TaskRow
    token: str
    run_started: bool


def token_hash(token: str) -> str:
    """The SHA-256 of a task token, hex encoded — what the row stores."""

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def claim_statement(dialect: str, limit: int, workflows: Sequence[str]) -> Select[Any]:
    """The dispatch-order select of 04, for ``dialect``.

    Transcribed from the document, including the shape of the two
    ``CASE`` expressions. They look redundant next to ``explicit DESC``
    and are not: ``explicit DESC`` splits the rows into two groups, and
    each ``CASE`` is non-``NULL`` in exactly one of them, so neither
    group's ordering ever depends on where the backend sorts ``NULL``
    (SQLite first, PostgreSQL last on ``ASC``).

    On PostgreSQL the select locks the task rows it returns and skips the
    ones another claimer already holds. The lock is ``OF tasks``: locking
    the joined run as well would make two claims of different tasks in
    one run exclude each other, which is the opposite of what
    ``SKIP LOCKED`` is here for.
    """

    statement = (
        select(tasks.c.id)
        .select_from(tasks.join(runs, runs.c.id == tasks.c.run_id))
        .where(
            tasks.c.status == TaskStatus.ready.value,
            runs.c.status.in_(CLAIMABLE_RUNS),
            runs.c.workflow.in_(list(workflows)),
        )
        .order_by(
            runs.c.position.asc(),
            tasks.c.explicit.desc(),
            case((tasks.c.explicit, tasks.c.priority)).asc(),
            case((~tasks.c.explicit, tasks.c.priority)).asc(),
            tasks.c.created.desc(),
            tasks.c.id.desc(),
        )
        .limit(limit)
    )
    if dialect == POSTGRESQL:
        return statement.with_for_update(skip_locked=True, of=tasks)
    if dialect == SQLITE:
        return statement
    raise unsupported_dialect(dialect, "claim_ready")


def branch_path(row: TaskRow) -> tuple[int, ...]:
    """A task's place in the fan-out tree: its frame indexes, outermost first.

    The sort key of 04 §Routing edge cases. A task at top level has an
    empty path, which sorts before every branch of it — a tuple is
    compared element by element and a prefix is the smaller value.
    """

    return tuple(frame.index for frame in row.branch)


class TaskRepo(Repo):
    """Queries over ``tasks`` (07 §Schema)."""

    async def enqueue(
        self,
        run_id: str,
        node: str,
        payload: Any,
        priority: int,
        explicit: bool,
        attempt: int = 1,
        created: datetime | None = None,
        lineage: dict[str, Any] | None = None,
        branch: Sequence[BranchFrame] = (),
    ) -> TaskRow:
        """Add a ``ready`` task and return it.

        ``created`` defaults to now. A retry passes the failed attempt's
        value instead (04 §Running an attempt): ``created DESC`` is the
        dispatch order's last tiebreaker, so a retry that took a fresh
        timestamp would overtake everything enqueued while its first
        attempt ran.

        ``branch`` is the fan-out frame stack the task runs under,
        outermost first; a top-level task has none. ``priority`` and
        ``explicit`` are the dispatch key inside the run — the run's own
        position is read through the join at claim time and is not
        snapshotted here (D41).
        """

        result = await self.conn.execute(
            tasks.insert()
            .values(
                run_id=run_id,
                node=node,
                attempt=attempt,
                status=TaskStatus.ready.value,
                payload=payload,
                result=None,
                error=None,
                priority=priority,
                explicit=explicit,
                token_hash=None,
                stats=None,
                lineage=lineage,
                terminal=False,
                branch=[frame.model_dump() for frame in branch],
                created=now() if created is None else created,
                started=None,
                finished=None,
            )
            .returning(*tasks.c)
        )
        row = self._first(TaskRow, result)
        if row is None:  # pragma: no cover - an INSERT ... RETURNING has a row
            raise RuntimeError("the task insert returned no row")
        return row

    async def get(self, task_id: int) -> TaskRow | None:
        """One attempt, or ``None``."""

        result = await self.conn.execute(select(tasks).where(tasks.c.id == task_id))
        return self._first(TaskRow, result)

    async def list_for_run(self, run_id: str) -> list[TaskRow]:
        """Every attempt of a run, oldest first.

        By ``id``: it is the order the rows were written in, which a
        timeline reads as the order things happened. Two attempts can
        share a ``created`` — a retry keeps its predecessor's — so that
        column cannot carry the ordering.
        """

        result = await self.conn.execute(
            select(tasks).where(tasks.c.run_id == run_id).order_by(tasks.c.id)
        )
        return self._rows(TaskRow, result)

    async def by_token_hash(self, hash_: str) -> TaskRow | None:
        """The attempt a task token belongs to, or ``None``.

        A miss is ``None``, not an exception: an unknown token is the
        ordinary case at the door of ``/api/agent/`` and the caller
        answers 403 either way (12 §Task tokens). Whether the attempt is
        still live is the caller's check too — this is a lookup, not an
        authorisation.
        """

        result = await self.conn.execute(
            select(tasks).where(tasks.c.token_hash == hash_)
        )
        return self._first(TaskRow, result)

    async def finish(
        self,
        task_id: int,
        status: str,
        result: Any = None,
        error: str | None = None,
        terminal: bool = False,
    ) -> TaskRow | None:
        """End an attempt: its status, its outcome, and ``finished``.

        ``terminal`` marks a task that finished ``done`` with no
        transitions, so its ``result`` is a branch output (04 §Routing
        edge cases). ``None`` if there is no such task.
        """

        outcome = await self.conn.execute(
            tasks.update()
            .where(tasks.c.id == task_id)
            .values(
                status=str(status),
                result=result,
                error=error,
                terminal=terminal,
                finished=now(),
            )
            .returning(*tasks.c)
        )
        return self._first(TaskRow, outcome)

    async def set_status(self, task_id: int, status: str) -> TaskRow | None:
        """Move an attempt to ``status`` and nothing else.

        No timestamp is written: an operator moving a task back to
        ``ready`` has not finished it, and ``started`` belongs to the
        claim. :meth:`finish` is the call that ends an attempt.
        """

        result = await self.conn.execute(
            tasks.update()
            .where(tasks.c.id == task_id)
            .values(status=str(status))
            .returning(*tasks.c)
        )
        return self._first(TaskRow, result)

    async def set_stats(
        self, task_id: int, stats: dict[str, Any] | None
    ) -> TaskRow | None:
        """Record this attempt's agent stats entry (05 §Stats entry).

        One entry per attempt, so a run's totals are a ``SUM`` over this
        column rather than an event scan (07 §Repositories). The entry
        replaces whatever was there: it is written once, when the agent
        call ends.
        """

        result = await self.conn.execute(
            tasks.update()
            .where(tasks.c.id == task_id)
            .values(stats=stats)
            .returning(*tasks.c)
        )
        return self._first(TaskRow, result)

    async def last_for_node(self, run_id: str, node: str) -> TaskRow | None:
        """The newest attempt at ``node`` in this run, or ``None``.

        What a rerun reads: it starts a fresh attempt at a node with the
        payload and branch stack the last one had (04 §Operator
        operations), so a rerun of a fanned-out node stays in its branch.
        """

        result = await self.conn.execute(
            select(tasks)
            .where(tasks.c.run_id == run_id, tasks.c.node == node)
            .order_by(tasks.c.id.desc())
            .limit(1)
        )
        return self._first(TaskRow, result)

    async def has_pending(self, run_id: str) -> bool:
        """Whether the run still has a ``ready``, ``in_progress`` or ``waiting``
        task.

        The question the runner asks before completing a run: a terminal
        task with siblings still outstanding ends its own branch, not the
        run (04 §Running an attempt).
        """

        result = await self.conn.execute(
            select(tasks.c.id)
            .where(tasks.c.run_id == run_id, tasks.c.status.in_(PENDING))
            .limit(1)
        )
        return result.first() is not None

    async def terminal_tasks(self, run_id: str) -> list[TaskRow]:
        """The run's terminal attempts, in branch order.

        Branch order is the frame index path, outermost first (04 §Routing
        edge cases): it is what makes a fan-out's output a deterministic
        list rather than one ordered by which branch happened to finish
        first. It is a path through a JSON array, so it is applied in
        Python over the frames the read model parsed; ``id`` breaks a tie
        between two terminal tasks of the same branch.
        """

        result = await self.conn.execute(
            select(tasks).where(
                tasks.c.run_id == run_id,
                tasks.c.terminal.is_(True),
            )
        )
        rows = self._rows(TaskRow, result)
        return sorted(rows, key=lambda row: (branch_path(row), row.id))

    async def reset_for_recovery(
        self, workflows: Sequence[str] | None = None
    ) -> list[int]:
        """Return every interrupted attempt to ``ready``; report which.

        Step 1 of 04 §Recovery on startup. A crash and a graceful stop
        leave the same rows behind — ``in_progress`` or ``waiting``, with
        no status written by the shutdown — and both re-execute from
        scratch. Nothing else is touched: ``done``, ``failed``,
        ``dead_letter`` and ``cancelled`` are decisions somebody made, and
        ``cancelled`` in particular is operator intent that recovery must
        not undo.

        ``token_hash`` is cleared with the status. The next claim mints a
        fresh token, so a token captured from the attempt that died
        authenticates nothing (D38, 12 §Task tokens).

        ``workflows`` narrows the sweep to the runs of those workflows —
        step 2 of the same section: a run whose workflow this server does
        not have registered is left exactly as it is, because nothing can
        claim it and a row reset to ``ready`` under it would read as work
        that is about to happen forever. ``None`` is the whole store,
        which is what a caller with no registry (a migration, a test) is
        asking for; an **empty sequence** is a registry with nothing in
        it and resets nothing, so the two cannot be conflated here.
        """

        statement = tasks.update().where(tasks.c.status.in_(INTERRUPTED))
        if workflows is not None:
            statement = statement.where(
                tasks.c.run_id.in_(
                    select(runs.c.id).where(runs.c.workflow.in_(list(workflows)))
                )
            )
        result = await self.conn.execute(
            statement.values(
                status=TaskStatus.ready.value,
                started=None,
                token_hash=None,
            ).returning(tasks.c.id)
        )
        return sorted(int(row_id) for row_id in result.scalars())

    async def claim_ready(
        self, limit: int, workflows: Sequence[str]
    ) -> list[ClaimedTask]:
        """Take up to ``limit`` ready tasks of ``workflows``, in dispatch order.

        The whole of 04 §Dispatch order in one call, and it must run
        inside a unit of work: selecting, claiming and starting the run
        are one transaction.

        1. Select the ids in dispatch order (:func:`claim_statement`).
        2. Mint a token per id and hash it.
        3. ``UPDATE … WHERE id = ? AND status = 'ready'`` — that predicate
           *is* the claim. A rowcount of 0 means another claimer won the
           row, and the id is dropped rather than raising: losing a race
           is the normal outcome of one, not an error.
        4. Flip each distinct run still ``queued`` to ``running``, and
           flag the first claimed task of each one it moved, so the
           caller emits ``run.started`` once per run.
        5. Re-select the claimed rows and return them in claimed order,
           each with its clear-text token.

        An empty ``workflows`` — a pool with nothing registered on it —
        and a non-positive ``limit`` — a pool with no free slot — claim
        nothing and ask the database nothing.
        """

        if limit <= 0 or not workflows:
            return []
        selected = await self.conn.execute(
            claim_statement(self.dialect, limit, workflows)
        )
        ids = [int(task_id) for task_id in selected.scalars()]
        if not ids:
            return []

        stamp = now()
        won: list[tuple[int, str]] = []
        for task_id in ids:
            token = secrets.token_urlsafe(TOKEN_BYTES)
            outcome = await self.conn.execute(
                tasks.update()
                .where(
                    tasks.c.id == task_id,
                    tasks.c.status == TaskStatus.ready.value,
                )
                .values(
                    status=TaskStatus.in_progress.value,
                    started=stamp,
                    token_hash=token_hash(token),
                )
            )
            if outcome.rowcount == 1:
                won.append((task_id, token))
        if not won:
            return []

        claimed = await self.conn.execute(
            select(tasks).where(tasks.c.id.in_([task_id for task_id, _ in won]))
        )
        rows = {row.id: row for row in self._rows(TaskRow, claimed)}

        ordered = [(rows[task_id], token) for task_id, token in won]
        started = await self._start_runs(
            list(dict.fromkeys(row.run_id for row, _ in ordered)), stamp
        )
        announced: set[str] = set()
        result: list[ClaimedTask] = []
        for row, token in ordered:
            first = row.run_id in started and row.run_id not in announced
            announced.add(row.run_id)
            result.append(ClaimedTask(row, token, first))
        return result

    async def _start_runs(self, run_ids: Sequence[str], stamp: datetime) -> set[str]:
        """Flip each ``queued`` run in ``run_ids`` to ``running``.

        Returns the ones that moved. The ``AND status = 'queued'`` is what
        makes "this claim started the run" a fact the database decided:
        a run already ``running`` reports nothing, so ``run.started`` is
        emitted once in the life of a run however many claims it takes.
        """

        started: set[str] = set()
        for run_id in run_ids:
            outcome = await self.conn.execute(
                runs.update()
                .where(
                    runs.c.id == run_id,
                    runs.c.status == RunStatus.queued.value,
                )
                .values(status=RunStatus.running.value, updated=stamp)
            )
            if outcome.rowcount == 1:
                started.add(run_id)
        return started


__all__ = [
    "CLAIMABLE_RUNS",
    "INTERRUPTED",
    "PENDING",
    "TOKEN_BYTES",
    "ClaimedTask",
    "TaskRepo",
    "branch_path",
    "claim_statement",
    "token_hash",
]

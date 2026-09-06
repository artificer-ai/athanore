"""The submission repository: the values an agent submitted.

03 §Submission: only payloads that passed the declared ``output_model``
are stored, and the latest wins for the body. Submissions are append-only
and never route anything (invariant 1 of 03) — an agent submits a value,
the node body decides what it means — so there is no update here and no
status.

:meth:`SubmissionRepo.latest` is the one the body reads: an agent that
was asked to repair its output submits again, and the newest row is the
answer, not the first.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from athanore.store.clock import now
from athanore.store.repos.base import Repo
from athanore.store.rows import SubmissionRow
from athanore.store.tables import submissions


class SubmissionRepo(Repo):
    """Queries over ``submissions`` (07 §Schema)."""

    async def insert(self, task_id: int, payload: Any) -> SubmissionRow:
        """Record one submission for a task attempt."""

        result = await self.conn.execute(
            submissions.insert()
            .values(task_id=task_id, payload=payload, created=now())
            .returning(*submissions.c)
        )
        row = self._first(SubmissionRow, result)
        if row is None:  # pragma: no cover - an INSERT ... RETURNING has a row
            raise RuntimeError("the submission insert returned no row")
        return row

    async def latest(self, task_id: int) -> SubmissionRow | None:
        """The newest submission of a task, or ``None``.

        By ``id``, not by ``created``: two submissions of one repair turn
        can share a timestamp at the store's resolution, and the id is the
        order they were written in.
        """

        result = await self.conn.execute(
            select(submissions)
            .where(submissions.c.task_id == task_id)
            .order_by(submissions.c.id.desc())
            .limit(1)
        )
        return self._first(SubmissionRow, result)

    async def list(self, task_id: int) -> list[SubmissionRow]:
        """Every submission of a task, oldest first."""

        result = await self.conn.execute(
            select(submissions)
            .where(submissions.c.task_id == task_id)
            .order_by(submissions.c.id)
        )
        return self._rows(SubmissionRow, result)


__all__ = ["SubmissionRepo"]

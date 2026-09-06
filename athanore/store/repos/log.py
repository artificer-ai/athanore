"""The work-log repository: append-only, read by cursor.

03 §LogEntry fixes the shape — a run, a node, an author, prose, and an
optional ``kind`` — and the log is append-only: there is no update and no
delete here, because an entry that can be edited is not an audit trail.
Removing one only ever happens with its run (07 §Retention).

``exclude_kinds`` is what the agent-facing view of the log uses (08
§Agent-facing): an agent reading the run's deliverables should not have
to page through a ``[stats]`` line per attempt.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import or_, select

from athanore.store.clock import now
from athanore.store.repos.base import Repo
from athanore.store.rows import LogEntryRow
from athanore.store.tables import log_entries


class LogRepo(Repo):
    """Queries over ``log_entries`` (07 §Schema)."""

    async def append(
        self,
        run_id: str,
        node: str,
        author: str,
        text: str,
        task_id: int | None = None,
        kind: str | None = None,
    ) -> LogEntryRow:
        """Add one entry and return it.

        ``task_id`` is optional because an entry may be about the run
        rather than an attempt — an operator note, an engine line written
        before any task existed.
        """

        result = await self.conn.execute(
            log_entries.insert()
            .values(
                run_id=run_id,
                task_id=task_id,
                node=node,
                author=str(author),
                kind=None if kind is None else str(kind),
                text=text,
                created=now(),
            )
            .returning(*log_entries.c)
        )
        row = self._first(LogEntryRow, result)
        if row is None:  # pragma: no cover - an INSERT ... RETURNING has a row
            raise RuntimeError("the log insert returned no row")
        return row

    async def list(
        self,
        run_id: str,
        after: int = 0,
        limit: int | None = None,
        exclude_kinds: Sequence[str] = (),
    ) -> list[LogEntryRow]:
        """A run's entries after the ``after`` cursor, oldest first.

        ``exclude_kinds`` drops entries of those kinds. An entry with no
        kind is never excluded — ``kind NOT IN (…)`` is ``NULL`` for a
        ``NULL`` kind, which SQL treats as false, so the ``IS NULL`` arm
        is what keeps the plain entries in the result.
        """

        statement = select(log_entries).where(
            log_entries.c.run_id == run_id, log_entries.c.id > after
        )
        if exclude_kinds:
            excluded = [str(kind) for kind in exclude_kinds]
            statement = statement.where(
                or_(
                    log_entries.c.kind.is_(None),
                    log_entries.c.kind.notin_(excluded),
                )
            )
        statement = statement.order_by(log_entries.c.id)
        if limit is not None:
            statement = statement.limit(limit)
        return self._rows(LogEntryRow, await self.conn.execute(statement))


__all__ = ["LogRepo"]

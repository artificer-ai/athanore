"""The event repository: the outbox's write path and the SSE cursor's reads.

``events.id`` is the cursor every subscriber replays by (08 §Events), so
two properties matter more than anything else here:

- **Ids ascend in emission order.** :meth:`EventRepo.insert_many` is one
  statement with ``RETURNING`` and ``sort_by_parameter_order``, so the id
  the caller gets back for its second event is greater than the one for
  its first. It is the write path
  :class:`~athanore.store.uow.UnitOfWork` flushes its outbox through, so
  there is one way an event becomes a row.
- **A glob selects whole segments.** ``run.*`` selects ``run.created``
  and not ``run.a.b`` — the rule
  :func:`athanore.events.names.matches` states for the bus, enforced here
  in SQL so a filtered replay and a filtered live stream agree. ``store``
  and ``events`` are independent siblings of the bottom tier (02
  §Layering), so this module restates the rule rather than importing it,
  the same way :class:`~athanore.store.rows.EventRow` restates the
  envelope (D81); ``tests/store/test_events_repo.py`` asserts the two
  agree.

The translation is exact for the ``*`` and ``?`` wildcards: a wildcard
match plus a check that the name has exactly as many dots as the pattern.
Each literal dot in the pattern consumes one dot of the name, so equal dot
counts mean no wildcard swallowed a separator, which is the whole of the
one-segment rule. ``fnmatch`` character classes (``[abc]``) have no
``LIKE`` equivalent and are refused rather than silently mismatched (D87).

**The wildcard match is the one part that is spelled per backend.**
:func:`~athanore.events.names.matches` is ``fnmatchcase``, so the rule is
case-sensitive: ``RUN.*`` selects nothing, because no event is named
``RUN.created``. PostgreSQL's ``LIKE`` is case-sensitive and says the
same. SQLite's is *not* — it folds ASCII case — so a ``LIKE`` there
selects ``run.created`` for the pattern ``RUN.*`` while the bus does not,
and a filtered replay hands a subscriber events its live stream will
never deliver. SQLite's ``GLOB`` is case-sensitive and its syntax is
``fnmatch``'s, so that is what this module emits there (D89). The dot
count is the same expression on both.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import ColumnElement, and_, func, or_, select

from athanore.store.repos.base import (
    POSTGRESQL,
    SQLITE,
    Repo,
    unsupported_dialect,
)
from athanore.store.rows import EventRow
from athanore.store.tables import events

#: The ``LIKE`` escape character. Backslash is not special to PostgreSQL
#: ``LIKE`` unless declared, which is what ``ESCAPE`` does.
LIKE_ESCAPE = "\\"

#: Characters ``LIKE`` treats as wildcards, plus the escape itself.
_LIKE_SPECIAL = frozenset({"%", "_", LIKE_ESCAPE})

#: The prefix :meth:`EventRepo.prune` keeps by default: a run's lifecycle
#: outlives its noise, so an old run is still readable (07 §Retention).
RUN_PREFIX = "run."


class OutboxEvent(Protocol):
    """The shape :meth:`EventRepo.insert_many` needs of an event.

    ``athanore.events.model.Event`` satisfies it. ``id`` is writable
    because assigning it is how the insert hands the SSE cursor back to
    the caller that emitted the event.
    """

    id: int | None
    run_id: str | None
    task_id: int | None
    name: str
    data: dict[str, Any]
    created: datetime


def like_pattern(pattern: str) -> str:
    """``pattern`` as a ``LIKE`` pattern: ``*`` → ``%``, ``?`` → ``_``.

    Everything else is a literal, so the ``LIKE`` wildcards a caller's
    pattern happens to contain are escaped rather than honoured. This is
    the PostgreSQL spelling; SQLite takes the pattern unchanged, because
    ``GLOB`` reads ``*`` and ``?`` itself and has no other metacharacter
    once ``[`` is refused.
    """

    out: list[str] = []
    for character in pattern:
        if character == "*":
            out.append("%")
        elif character == "?":
            out.append("_")
        elif character in _LIKE_SPECIAL:
            out.append(LIKE_ESCAPE + character)
        else:
            out.append(character)
    return "".join(out)


def glob_condition(
    column: ColumnElement[str], pattern: str, dialect: str
) -> ColumnElement[bool]:
    """The SQL for "``column`` matches the dotted glob ``pattern``".

    See the module docstring for why a wildcard match and a dot count are
    the whole rule, and why the wildcard half is ``GLOB`` on SQLite and
    ``LIKE`` on PostgreSQL.
    """

    if "[" in pattern or "]" in pattern:
        raise ValueError(
            f"event pattern {pattern!r} uses a character class, which the "
            "store's glob does not support; use * and ? only"
        )
    if dialect == SQLITE:
        wildcards = column.bool_op("GLOB")(pattern)
    elif dialect == POSTGRESQL:
        wildcards = column.like(like_pattern(pattern), escape=LIKE_ESCAPE)
    else:
        raise unsupported_dialect(dialect, "the event-name glob")
    dots = func.length(column) - func.length(func.replace(column, ".", ""))
    return and_(wildcards, dots == pattern.count("."))


class EventRepo(Repo):
    """Queries over ``events`` (07 §Schema)."""

    async def insert_many(self, batch: Sequence[OutboxEvent]) -> list[int]:
        """Insert ``batch`` in order and return the ids it was given.

        One statement. ``sort_by_parameter_order`` is what makes the
        returned ids line up with the events that were passed in:
        without it SQLAlchemy is free to hand back ``RETURNING`` rows in
        whatever order the backend produced them, and an id that names
        the wrong event is a cursor into the wrong place.
        """

        if not batch:
            return []
        result = await self.conn.execute(
            events.insert().returning(events.c.id, sort_by_parameter_order=True),
            [
                {
                    "run_id": event.run_id,
                    "task_id": event.task_id,
                    "name": event.name,
                    "data": event.data,
                    "created": event.created,
                }
                for event in batch
            ],
        )
        return [int(row[0]) for row in result]

    async def list_after(
        self,
        after: int,
        limit: int,
        run_id: str | None = None,
        patterns: Sequence[str] | None = None,
    ) -> list[EventRow]:
        """The events after the ``after`` cursor, oldest first.

        ``patterns`` selects by name: an event matching any one of them is
        kept. An empty sequence is not a filter that matches nothing — it
        is no filter, the same as ``None``, because "give me no names" is
        never what a caller means.
        """

        statement = select(events).where(events.c.id > after)
        if run_id is not None:
            statement = statement.where(events.c.run_id == run_id)
        if patterns:
            statement = statement.where(
                or_(
                    *(
                        glob_condition(events.c.name, pattern, self.dialect)
                        for pattern in patterns
                    )
                )
            )
        statement = statement.order_by(events.c.id).limit(limit)
        return self._rows(EventRow, await self.conn.execute(statement))

    async def list_for_run(
        self, run_id: str, after: int = 0, limit: int | None = None
    ) -> list[EventRow]:
        """One run's events after ``after``, oldest first."""

        statement = (
            select(events)
            .where(events.c.run_id == run_id, events.c.id > after)
            .order_by(events.c.id)
        )
        if limit is not None:
            statement = statement.limit(limit)
        return self._rows(EventRow, await self.conn.execute(statement))

    async def prune(self, before: datetime, keep_prefix: str = RUN_PREFIX) -> int:
        """Delete events older than ``before``, keeping ``keep_prefix``.

        Returns the number of rows removed. ``keep_prefix=""`` keeps
        nothing. Nothing here decides *when* to prune: the schedule is
        T017's, and the retention window is a setting.

        The prefix is compared with ``substr`` and ``=`` rather than a
        ``LIKE``: equality is case-sensitive on both backends, where
        SQLite's ``LIKE`` would fold ASCII case and keep a ``RUN.``
        event PostgreSQL deleted (D89). It also leaves nothing to escape,
        so a prefix containing ``%`` or ``_`` is a prefix.
        """

        statement = events.delete().where(events.c.created < before)
        if keep_prefix:
            statement = statement.where(
                func.substr(events.c.name, 1, len(keep_prefix)) != keep_prefix
            )
        result = await self.conn.execute(statement)
        return result.rowcount


__all__ = [
    "LIKE_ESCAPE",
    "RUN_PREFIX",
    "EventRepo",
    "OutboxEvent",
    "glob_condition",
    "like_pattern",
]

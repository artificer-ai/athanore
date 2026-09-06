"""What every repository shares: a connection, a dialect, and row conversion.

There is no ORM in this build. A repository runs Core statements on one
connection and hands out the frozen read models of
:mod:`athanore.store.rows`, so nothing can lazy-load across a closed
connection and a row cannot drift after the transaction that produced it
ended (07 §Repositories).

Two things are worth stating once, here, rather than in five repositories:

- **A connection, not an engine.** A repository never opens or commits
  anything. It is constructed around the connection it was given —
  the :class:`~athanore.store.uow.UnitOfWork`'s transaction, or a pooled
  read connection — which is what makes "every state change is one
  transaction" a property of the caller's block rather than a convention
  each method has to remember.
- **Timestamps come back aware.** SQLite has no timestamp type: a
  ``DateTime(timezone=True)`` column round-trips through ``TEXT`` and
  returns a *naive* value, where PostgreSQL returns an aware one.
  The store only ever writes UTC (:func:`athanore.store.uow.now`), so
  :meth:`Repo._row` stamps ``UTC`` onto the naive ones and the two
  backends produce equal read models (D87).

A handful of statements differ between the two backends —
``GROUP_CONCAT`` against ``string_agg``, ``json_extract`` against
``jsonb_extract_path_text``. :attr:`Repo.dialect` is how a repository
asks, and the expression builders that branch on it are module-level
functions taking the dialect name, so a test can compile both without a
server of either kind.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, TypeVar

from sqlalchemy import CursorResult, RowMapping
from sqlalchemy.ext.asyncio import AsyncConnection

from athanore.store.rows import ReadModel

#: The two dialect names the store knows. Anything else is a backend
#: nobody has written the queries for, and a repository says so rather
#: than silently emitting SQLite's spelling at it.
SQLITE = "sqlite"
POSTGRESQL = "postgresql"

M = TypeVar("M", bound=ReadModel)


def aware(value: object) -> object:
    """``value``, with UTC attached if it is a naive datetime.

    Only datetimes are touched. See the module docstring for why.
    """

    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def unsupported_dialect(dialect: str, what: str) -> NotImplementedError:
    """The error a dialect switch raises for a backend it does not know."""

    return NotImplementedError(
        f"{what} has no implementation for the {dialect!r} dialect; "
        f"athanore supports {SQLITE!r} and {POSTGRESQL!r} (07)"
    )


class Repo:
    """A repository bound to one connection.

    Subclasses add query methods and nothing else: no state, no caching,
    no lifecycle. Constructing one is free, which is what lets
    :class:`~athanore.store.uow.UnitOfWork` and
    :class:`~athanore.store.uow.Reader` each own a full set.
    """

    def __init__(self, conn: AsyncConnection) -> None:
        self.conn = conn

    @property
    def dialect(self) -> str:
        """The name of the backend this connection speaks."""

        return self.conn.dialect.name

    @property
    def is_sqlite(self) -> bool:
        """Whether this connection speaks SQLite."""

        return self.dialect == SQLITE

    def _row(self, model: type[M], row: RowMapping | Mapping[str, Any]) -> M:
        """One read model from one row mapping.

        A :class:`~sqlalchemy.engine.RowMapping` satisfies the parameter,
        and so does a plain dict — which is what a query with computed
        columns (``RunRepo.list``) builds before validating.
        """

        return model.model_validate({key: aware(value) for key, value in row.items()})

    def _rows(self, model: type[M], result: CursorResult[Any]) -> list[M]:
        """Every row of ``result`` as a read model, in the order selected."""

        return [self._row(model, mapping) for mapping in result.mappings()]

    def _first(self, model: type[M], result: CursorResult[Any]) -> M | None:
        """The first row of ``result``, or ``None`` when it has none."""

        mapping = result.mappings().first()
        return None if mapping is None else self._row(model, mapping)


__all__ = [
    "POSTGRESQL",
    "SQLITE",
    "Repo",
    "aware",
    "unsupported_dialect",
]

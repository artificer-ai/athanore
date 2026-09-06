"""The store's clock.

One function, in a module of its own, because everything in ``store``
needs it and two of the things that need it — :mod:`athanore.store.uow`
and the repositories it owns — point at each other. Importing it from
here keeps that arrow absent.

Every timestamp column in :mod:`athanore.store.tables` is
``DateTime(timezone=True)``. A naive value written into one is stored
differently by SQLite and by PostgreSQL and read back differently again,
so the store never produces one.
"""

from __future__ import annotations

from datetime import UTC, datetime


def now() -> datetime:
    """The current time, timezone-aware and in UTC."""

    return datetime.now(UTC)


__all__ = ["now"]

"""One repository per aggregate.

Each is a thin, typed set of Core queries over one table, constructed
around a connection and returning the frozen read models of
:mod:`athanore.store.rows` (07 §Repositories). They are reached through
:class:`~athanore.store.uow.UnitOfWork` for writes and
:class:`~athanore.store.uow.Reader` for reads, never constructed by a
caller a tier up.
"""

from athanore.store.repos.base import Repo
from athanore.store.repos.runs import RunRepo

__all__ = [
    "Repo",
    "RunRepo",
]

"""One repository per aggregate.

Each is a thin, typed set of Core queries over one table, constructed
around a connection and returning the frozen read models of
:mod:`athanore.store.rows` (07 §Repositories). They are reached through
:class:`~athanore.store.uow.UnitOfWork` for writes and
:class:`~athanore.store.uow.Reader` for reads, never constructed by a
caller a tier up.
"""

from athanore.store.repos.base import Repo
from athanore.store.repos.events import EventRepo, OutboxEvent
from athanore.store.repos.log import LogRepo
from athanore.store.repos.runs import RunRepo
from athanore.store.repos.submissions import SubmissionRepo

__all__ = [
    "EventRepo",
    "LogRepo",
    "OutboxEvent",
    "Repo",
    "RunRepo",
    "SubmissionRepo",
]

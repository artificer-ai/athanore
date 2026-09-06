"""The periodic prune (07 §Retention).

Two rows in the schema grow without bound while everything else is
proportional to the work an operator asked for: the agent transcript, at
two to three flushes a second per streaming task (D19), and the event
log, which carries every state change in the process. 07 §Retention puts
a window on each, and this module is the job that enforces them —
:func:`prune_once` for one pass, :func:`retention_loop` for the hourly
schedule the server starts.

Two rules, and they are not the same rule:

- **Stream chunks** age from the attempt *finishing*, not from the chunk
  being written, so a long turn is never pruned out from under a reader
  and a running task keeps its transcript however old. The work log keeps
  the deliverables; the transcript is diagnostic.
- **Events** age from the row, and ``run.*`` is exempt: a run's own
  lifecycle outlives its noise, which is what makes an old run still
  readable in the list and in 18's "the last event of a run".

Nothing here writes SQL. Both windows are one call to a query T014a and
T014b already own — :meth:`~athanore.store.repos.stream.StreamRepo.prune_finished`
and :meth:`~athanore.store.repos.events.EventRepo.prune` — because there
is one place a table is deleted from, and a schedule is not a reason for
a second one.

Deleting a *run* is the third rule of 07 §Retention and is not on a
timer: it is
:meth:`~athanore.store.repos.runs.RunRepo.delete`, whose cascade takes
every child table with it (D83), and it happens when an operator asks.

The windows are settings (``settings.retention``, 02 §Configuration), and
``store`` may not import ``athanore.settings``: they are independent
siblings of the bottom tier (02 §Layering). :class:`Retention` therefore
names the shape rather than the class, the way
:class:`~athanore.store.uow.EventPublisher` names the bus (D86). The
concrete type is ``athanore.settings.Retention`` and the caller a tier up
passes it in.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import NamedTuple, Protocol

from athanore.store.clock import now as utcnow
from athanore.store.repos.events import RUN_PREFIX
from athanore.store.uow import Store

#: How often :func:`retention_loop` prunes: hourly, per 07 §Retention.
PRUNE_INTERVAL = 3600.0


class Retention(Protocol):
    """The two windows, in days (``athanore.settings.Retention``).

    Structural rather than imported, so ``store`` keeps no arrow to its
    sibling ``settings`` (02 §Layering).
    """

    events_days: int
    stream_days: int


class PruneCounts(NamedTuple):
    """What one pass removed, per table.

    Real counts from the two ``DELETE`` statements, never an estimate: a
    caller that logs a pass reports what happened (`AGENTS.md` §Real data
    only).
    """

    #: Chunks deleted from ``stream_chunks``.
    stream_chunks: int
    #: Rows deleted from ``events``.
    events: int


async def prune_once(
    store: Store, retention: Retention, now: datetime | None = None
) -> PruneCounts:
    """Run one retention pass and return what it removed.

    ``now`` is the instant the two windows are measured back from; it
    defaults to the store's clock. Passing it is what lets a caller —
    a test under ``freezegun``, an operator pruning to a stated moment —
    make the ages exact rather than approximate.

    Both deletes are one transaction, so a pass either happens or does
    not: a crash between them would otherwise leave the two windows
    enforced to different instants. Nothing is emitted — a prune removes
    history rather than making any, and there is no ``retention.*`` name
    in the vocabulary (18).

    Errors are not caught. A failed pass rolls back and raises, and what
    happens next is the caller's decision, not the store's (rule 3).
    """

    moment = utcnow() if now is None else now
    async with store.uow() as uow:
        chunks = await uow.stream.prune_finished(
            moment - timedelta(days=retention.stream_days)
        )
        # `keep_prefix` is passed rather than left to its default so that
        # the `run.*` exemption of 07 §Retention is legible here, where
        # the schedule that applies it lives.
        events = await uow.events.prune(
            moment - timedelta(days=retention.events_days), keep_prefix=RUN_PREFIX
        )
    return PruneCounts(stream_chunks=chunks, events=events)


async def retention_loop(
    store: Store, retention: Retention, interval: float = PRUNE_INTERVAL
) -> None:
    """Prune every ``interval`` seconds until cancelled.

    The first pass runs immediately and the sleep follows it, so a
    process restarted more often than ``interval`` still prunes; the
    alternative sleeps first and, on a machine that is shut down nightly,
    never reaches the job at all.

    Cancellation is the only way out. :exc:`asyncio.CancelledError`
    propagates untouched — from the sleep, or from the transaction if a
    pass is in flight — so a shutdown that cancels this task does not
    wait an hour for it. Nothing else is caught either: an exception from
    a pass ends the loop and reaches whoever is supervising the task,
    because a janitor that swallowed its own failures would look alive
    while the database grew.

    Reading the windows on every pass rather than once is deliberate: the
    object is a settings model, and a reload that changes a window takes
    effect at the next pass without restarting the loop.
    """

    while True:
        await prune_once(store, retention)
        await asyncio.sleep(interval)


__all__ = ["PRUNE_INTERVAL", "PruneCounts", "Retention", "prune_once", "retention_loop"]

"""The transaction boundary, the writer lock, and the outbox.

Every state change in Athanore is one transaction (`AGENTS.md` §Durable by
default), and every transaction that matters emits an event. This module
is where both of those become true:

.. code-block:: python

    async with store.uow() as uow:
        task = await uow.tasks.finish(task_id, "done", result=...)
        uow.emit(Event(name="task.done", run_id=..., task_id=..., data=...))
    # rows inserted in the same transaction -> commit -> published

:meth:`UnitOfWork.emit` is not publishing. It appends to an in-transaction
outbox; the exit of the block inserts those rows, commits, releases the
writer lock and only then hands them to the bus. A subscriber therefore
never sees an event for work that rolled back, and the ids it sees ascend,
which is what makes ``events.id`` usable as the SSE cursor (08 §Events).
A crash between the commit and the fan-out loses the in-memory
notification and nothing else: the rows are there and clients resync by
cursor (07 §Unit of work and outbox).

The single :class:`asyncio.Lock` is SQLite's one writer made explicit
(07 §Concurrency): serialising writers in the process turns "database is
locked" into "wait your turn". Readers take :meth:`Store.read`, which
takes no lock and uses the pool, because a report query must never queue
behind a commit. A unit of work holds that lock for as long as its block
runs, which is why one may never span an await on a node body, an agent,
or a request wait.

Nothing here retries. A failed transaction rolls back and raises; what
happens next is the engine's decision, not the store's (rule 3).

Reads take :class:`Reader` instead, through :meth:`Store.reader`: the
same repositories on a pooled connection with no transaction and no lock,
so nothing a report query does is committed and nothing it does queues
behind a commit.

``store`` and ``events`` are independent siblings of the bottom tier
(02 §Layering), so the store names the two shapes it needs from the event
layer structurally — :class:`EventPublisher` here, and
:class:`~athanore.store.repos.events.OutboxEvent` beside the insert that
takes it — rather than importing ``athanore.events``. It is
the same constraint that made :class:`~athanore.store.rows.EventRow`
restate the envelope in T010 (D81). The concrete types are
``athanore.events.model.Event`` and ``athanore.events.bus.EventBus``, and
the engine, a tier up, is free to import both and wire them together.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from types import TracebackType
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncTransaction

from athanore.store.clock import now
from athanore.store.repos.events import EventRepo, OutboxEvent
from athanore.store.repos.joins import JoinRepo
from athanore.store.repos.log import LogRepo
from athanore.store.repos.requests import RequestRepo
from athanore.store.repos.runs import RunRepo
from athanore.store.repos.stream import StreamRepo
from athanore.store.repos.submissions import SubmissionRepo
from athanore.store.repos.tasks import TaskRepo


class Repos:
    """Every repository, bound to one connection.

    Constructing the set is free — a repository holds a connection and
    nothing else — so a unit of work and a reader each own one rather than
    sharing a registry with a lifecycle of its own.
    """

    def __init__(self, conn: AsyncConnection) -> None:
        self.conn = conn
        self.runs = RunRepo(conn)
        self.tasks = TaskRepo(conn)
        self.log = LogRepo(conn)
        self.events = EventRepo(conn)
        self.submissions = SubmissionRepo(conn)
        self.stream = StreamRepo(conn)
        self.requests = RequestRepo(conn)
        self.joins = JoinRepo(conn)


class Reader(Repos):
    """The repositories on a pooled read connection.

    Read-only by construction rather than by convention: :meth:`Store.read`
    hands out a connection with no transaction open on it, so a write
    method called here is rolled back when the block ends. Readers take no
    writer lock, because a report query must never queue behind a commit
    (07 §Concurrency).
    """


class EventPublisher(Protocol):
    """Somewhere to hand a committed event, synchronously.

    ``athanore.events.bus.EventBus`` satisfies it. The method must not be
    a coroutine: publishing happens with the writer lock just released and
    the transaction just closed, and awaiting a subscriber there is how a
    stalled SSE client would come to hold up every writer in the process.

    The parameter is typed ``Any`` rather than :class:`OutboxEvent`
    because a publisher is free to want the concrete envelope — an
    implementation that accepted only ``Event`` would not satisfy a
    protocol demanding it accept every structural match.
    """

    def publish(self, event: Any, /) -> None: ...


class UnitOfWork:
    """One write transaction and the events it will publish when it commits.

    Repositories are reached as attributes — ``uow.runs``, ``uow.log``,
    ``uow.events``, … — and share this transaction's connection, so
    everything done through them commits or rolls back together. Reaching
    one outside the block raises, for the same reason :meth:`emit` does.

    Instances come from :meth:`Store.uow`. A unit of work is entered once
    and is not reusable: the connection is released on the way out and
    :attr:`conn` raises after that.
    """

    def __init__(
        self,
        engine: AsyncEngine,
        bus: EventPublisher,
        writer_lock: asyncio.Lock,
    ) -> None:
        self._engine = engine
        self._bus = bus
        self._writer_lock = writer_lock
        self._outbox: list[OutboxEvent] = []
        self._conn: AsyncConnection | None = None
        self._tx: AsyncTransaction | None = None
        self._repos: Repos | None = None

    @property
    def conn(self) -> AsyncConnection:
        """The connection this transaction runs on."""
        return self._open()

    @property
    def runs(self) -> RunRepo:
        """The run repository, on this transaction."""
        return self._open_repos().runs

    @property
    def tasks(self) -> TaskRepo:
        """The task repository, on this transaction."""
        return self._open_repos().tasks

    @property
    def log(self) -> LogRepo:
        """The work-log repository, on this transaction."""
        return self._open_repos().log

    @property
    def events(self) -> EventRepo:
        """The event repository, on this transaction."""
        return self._open_repos().events

    @property
    def submissions(self) -> SubmissionRepo:
        """The submission repository, on this transaction."""
        return self._open_repos().submissions

    @property
    def stream(self) -> StreamRepo:
        """The transcript repository, on this transaction."""
        return self._open_repos().stream

    @property
    def requests(self) -> RequestRepo:
        """The request repository, on this transaction."""
        return self._open_repos().requests

    @property
    def joins(self) -> JoinRepo:
        """The join-arrival repository, on this transaction."""
        return self._open_repos().joins

    def emit(self, event: OutboxEvent) -> None:
        """Queue ``event`` for insertion and publication when this commits.

        Emitting is not publishing: nothing reaches the bus, and no row is
        written, until the transaction commits. If it rolls back the event
        is discarded with it.

        Emitting outside the block raises rather than appending to an
        outbox nothing will ever flush — an event that vanishes silently
        is a gap in the audit trail and in every SSE stream.
        """
        self._open()
        self._outbox.append(event)

    async def __aenter__(self) -> UnitOfWork:
        if self._conn is not None:
            raise RuntimeError("a unit of work cannot be entered twice")
        await self._writer_lock.acquire()
        conn: AsyncConnection | None = None
        try:
            conn = await self._engine.connect()
            self._tx = await conn.begin()
        except BaseException:
            if conn is not None:
                await conn.close()
            self._writer_lock.release()
            raise
        self._conn = conn
        self._repos = Repos(conn)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        conn, tx = self._conn, self._tx
        self._conn, self._tx, self._repos = None, None, None
        outbox, self._outbox = self._outbox, []
        if conn is None or tx is None:
            raise RuntimeError("the unit of work was never opened")
        try:
            if exc_type is None:
                await self._write_outbox(EventRepo(conn), outbox)
                await tx.commit()
            else:
                await tx.rollback()
        except BaseException:
            # The insert or the commit failed: nothing is stored, so no id
            # any of these events was stamped with names a row.
            for event in outbox:
                event.id = None
            if tx.is_active:
                await tx.rollback()
            raise
        finally:
            try:
                await conn.close()
            finally:
                self._writer_lock.release()
        if exc_type is None:
            # Committed and unlocked: only now is it true that a subscriber
            # woken by one of these can read the rows behind it.
            for event in outbox:
                self._bus.publish(event)

    def _open(self) -> AsyncConnection:
        """The live connection, or a :exc:`RuntimeError` naming the misuse."""
        if self._conn is None:
            raise RuntimeError(
                "the unit of work is not open; use `async with store.uow()`"
            )
        return self._conn

    def _open_repos(self) -> Repos:
        """The repositories, or a :exc:`RuntimeError` naming the misuse."""
        if self._repos is None:
            raise RuntimeError(
                "the unit of work is not open; use `async with store.uow()`"
            )
        return self._repos

    async def _write_outbox(
        self, repo: EventRepo, outbox: Sequence[OutboxEvent]
    ) -> None:
        """Insert the outbox and stamp each event with the id it was given.

        One statement, in emission order, so that the ids the caller gets
        back ascend in that order — ``events.id`` is the SSE cursor and a
        subscriber replays by it. That ordering is
        :meth:`EventRepo.insert_many`'s promise, which is why the outbox
        flushes through the repository rather than writing its own insert:
        there is one way an event becomes a row (D87).
        """
        ids = await repo.insert_many(outbox)
        for event, event_id in zip(outbox, ids, strict=True):
            event.id = event_id


class Store:
    """The database, its one writer, and the bus its commits publish to."""

    def __init__(self, engine: AsyncEngine, bus: EventPublisher) -> None:
        self.engine = engine
        self.bus = bus
        # SQLite has one writer; serialising them here is what keeps a
        # commit from meeting another commit (07 §Concurrency). It is held
        # for the whole of a `uow()` block, so those blocks stay short.
        self._writer_lock = asyncio.Lock()

    @asynccontextmanager
    async def uow(self) -> AsyncGenerator[UnitOfWork, None]:
        """A write transaction: the writer lock, a connection, and an outbox.

        The block commits on a clean exit and rolls back on an exception,
        which it re-raises. The order that matters — insert, commit,
        release the lock, publish — lives in
        :meth:`UnitOfWork.__aexit__`, so it is stated once.
        """
        async with UnitOfWork(self.engine, self.bus, self._writer_lock) as unit:
            yield unit

    @asynccontextmanager
    async def read(self) -> AsyncGenerator[AsyncConnection, None]:
        """A pooled read connection, taken without the writer lock.

        Reads never queue behind the writer: WAL lets a reader run against
        the last committed state while a transaction is open (07
        §Concurrency), and a long history query must not hold up a commit.
        Nothing written on this connection is committed.
        """
        async with self.engine.connect() as conn:
            yield conn

    @asynccontextmanager
    async def reader(self) -> AsyncGenerator[Reader, None]:
        """The repositories on a pooled read connection.

        The read-only half of :meth:`uow`: same queries, no transaction,
        no writer lock. It is what the API's ``GET`` handlers and the
        report queries of 08 use, so a long history read cannot hold up a
        commit (07 §Concurrency).
        """
        async with self.read() as conn:
            yield Reader(conn)

    async def publish_ephemeral(self, event: OutboxEvent) -> None:
        """Publish ``event`` to the bus without storing it.

        The path for ``task.stream`` (``EPHEMERAL`` in
        ``athanore.events.names``): two to three flushes a second per
        streaming task would be most of the ``events`` table, and the
        content is in ``stream_chunks`` for a late joiner to fetch anyway
        (03, 07 §Transcript writes). The event keeps its ``id`` of
        ``None``, which is what makes the SSE endpoint send it without an
        ``id:`` line.
        """
        self.bus.publish(event)


__all__ = [
    "EventPublisher",
    "OutboxEvent",
    "Reader",
    "Repos",
    "Store",
    "UnitOfWork",
    "now",
]

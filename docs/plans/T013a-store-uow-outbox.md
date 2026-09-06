# T013a — `Store`, `UnitOfWork`, outbox

**Task.** `docs/v1/17-serial-task-plan.md` § `### T013a`.
**Specs.** `docs/v1/07-storage.md` §Unit of work and §Outbox;
`AGENTS.md` §Architecture rules — "durable by default: every state
change is a transaction, every transaction that matters emits an event",
and "a UnitOfWork never spans an await on a node body, an agent, or a
request wait".

## What this task is

The transaction boundary for the whole system, and the outbox that makes
"committed" and "published" the same moment. Everything the engine and
the API later do to the database goes through this.

## What this task is not

- No repositories. T014–T016 attach them to `UnitOfWork`; this task
  leaves the attribute slots.
- No engine, no scheduler, no HTTP.
- Not a place for retry logic. A failed transaction rolls back and
  raises; rule 3 says the engine decides what happens next.

## Steps

1. `class Store(engine, bus)`:
   - `_writer_lock = asyncio.Lock()` — SQLite has one writer, and the
     lock is what turns "database is locked" into "wait your turn";
   - `async def uow() -> AsyncIterator[UnitOfWork]` — acquire the writer
     lock, open a connection, `begin()`;
   - `async def read() -> AsyncIterator[AsyncConnection]` — no lock,
     pooled: readers must never queue behind the writer;
   - `async def publish_ephemeral(event)` — bus only, never stored
     (T009's `EPHEMERAL`).
2. `class UnitOfWork`: holds `conn`, the repo attributes, and
   `emit(event)` which appends to `self._outbox` — emitting is not
   publishing.
3. `__aexit__` with no exception: insert the outbox rows with
   `RETURNING id`, set `event.id` on each, **commit**, release the lock,
   and only then `bus.publish` each in id order. On exception: roll
   back, drop the outbox, re-raise. A subscriber must never see an event
   for a transaction that did not commit, and ids must be ascending
   because SSE replay is ordered by them.
4. `now()` helper returning aware UTC — naive datetimes in a
   `DateTime(timezone=True)` column are a Postgres/SQLite divergence
   waiting to happen.

## Verification

`tests/store/test_uow.py`:

- emitting inside a uow that raises publishes nothing and stores nothing;
- two sequential uows produce ascending event ids;
- a subscriber sees the event only *after* commit — assert ordering, not
  just arrival;
- `publish_ephemeral` never writes a row;
- two concurrent `uow()` calls serialise rather than interleaving.

## Done

- Tests pass, including the concurrency one.
- `**Status.** Done.` on `### T013a`, in the same commit.

## Files

```
athanore/store/uow.py
tests/store/test_uow.py
docs/v1/17-serial-task-plan.md
```

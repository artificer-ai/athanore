# 07 — Storage

SQLAlchemy 2.0 **Core** (async engine, `Table` metadata, no ORM session)
with Alembic migrations. SQLite via `aiosqlite` is the default and the only backend the test suite runs against by default;
PostgreSQL via `asyncpg` is supported by configuration (`athanore[postgres]`)
and exercised in a nightly CI job. No raw SQL outside `store/`.

## Why change the MVP's store

The MVP's `store.py` works and is well tested, but it mixes four concerns
that v1 separates: persistence, schema evolution (hand-rolled
`PRAGMA table_info` upgrades in `__init__`), waiting/notification (an
`asyncio.Event` and a validator registry living on the store), and
blocking I/O (`sqlite3` under a `threading.Lock` on the event loop). The
`messages` table is polymorphic (`request` and `answer` rows in one table
with JSON `data`), and `delete_run` forgets it, leaving orphans. The
`events` table doubles as the agent transcript at 2–3 writes per second
per task with no retention.

## Schema

```
runs         id ULID PK, workflow, status, title, description, output JSON,
             position INT, created, updated, finished
             IX (position), IX (status)

tasks        id PK, run_id FK(runs) ON DELETE CASCADE, node, attempt,
             status, payload JSON, result JSON, error,
             priority INT, explicit BOOL,
             token_hash CHAR(64) NULL, stats JSON NULL, lineage JSON,
             terminal BOOL NOT NULL DEFAULT 0,                          -- done with no successors (04 §Routing edge cases)
             branch JSON NOT NULL DEFAULT '[]',                         -- fan-out frame stack (04 §Fan-in)
             created, started, finished
             IX (status, run_id)                                       -- claim: filter, then join runs(position)
             IX (run_id, id), IX (token_hash)

log_entries  id PK, run_id FK CASCADE, task_id FK NULL, node, author, kind, text, created
             IX (run_id, id)

submissions  id PK, task_id FK CASCADE, payload JSON, created
             IX (task_id, id)

stream_chunks id PK, task_id FK CASCADE, seq INT, kind, text, created
             UQ (task_id, seq)

requests     id PK, run_id FK CASCADE, task_id FK CASCADE, ordinal INT NULL,
             prompt, mode, source, kind,
             options JSON, schema JSON, tool_call JSON, created
             IX (run_id), UQ (task_id, ordinal) WHERE ordinal IS NOT NULL

answers      request_id PK FK(requests) CASCADE, author, option_id, value JSON,
             consumed BOOL, created

join_arrivals id PK, run_id FK CASCADE, join_node, fanout_task INT, index INT,
             key JSON, value JSON, from_task FK(tasks) NULL, late BOOL, created
             UQ (run_id, join_node, fanout_task, index)                -- upsert before the join fires

events       id PK (monotonic), run_id NULL, task_id NULL, name, data JSON, created
             IX (run_id, id), IX (name, id)

schema_version   (Alembic's alembic_version)
```

Notes:

- Foreign keys with cascade delete make `delete_run` one statement and
  fix the MVP's orphaned messages. `PRAGMA foreign_keys=ON` on every
  SQLite connection.
- `token_hash` replaces the clear-text `token` column. The token is
  generated **at claim** (04): the clear text is returned with the
  claimed row and lives only in the runner's memory; the column holds
  the hash and is NULL for `ready` tasks. Generating at enqueue, as the
  MVP did, is incompatible with hash-only storage (the clear text would
  have to survive until the claim, across restarts). Presented headers
  are hashed and compared with `hmac.compare_digest`.
- `tasks.stats` holds the agent stats entry (05) so `RunDetail` totals
  are one aggregate query.
- JSON columns use SQLAlchemy `JSON().with_variant(JSONB, "postgresql")`
  (`JSON1` on SQLite).
- `events.id` is the SSE cursor; it must be monotonic under one writer,
  which the UnitOfWork guarantees.

## Unit of work and outbox

```python
async with store.uow() as uow:
    task = await uow.tasks.finish(task_id, "done", result=…)
    await uow.tasks.enqueue(…)
    uow.emit(Event("task.done", run_id=…, task_id=…, data=…))
# commit → events inserted in the same transaction → EventBus.publish after commit
```

`emit()` appends to an in-transaction outbox; on commit the rows are
inserted and, after the commit succeeds, published to in-process
subscribers (SSE, plugin `on` handlers, request waiters). A crash between
insert and publish loses only the in-memory notification; SSE clients
resync from the store by cursor, so nothing is missed.

## Repositories

One per aggregate, thin, typed: `RunRepo`, `TaskRepo`, `LogRepo`,
`SubmissionRepo`, `StreamRepo`, `RequestRepo`, `EventRepo`, `JoinRepo`
(`arrive(...) -> (arrived, count)`, `arrivals(run, join, fanout) ->
list`, `incomplete(run) -> list[(join, fanout, arrived, count)]`). Query
methods return pydantic read models (`RunRow`, `TaskRow`, …) built from
Core `Row`s; there are no mapped classes, so nothing can lazy-load across
a closed connection and `expire_on_commit` never bites.

`TaskRepo.claim_ready(limit, workflows)` implements the ordering in 04:
select the ids in order, then one `UPDATE … WHERE id = ? AND status =
'ready'` per id — a token is minted per attempt, so each row is written a
different `token_hash`, and the `AND status` is the claim: rowcount 0
means another claimer won the row and the id is dropped. Then re-select
and return the rows in the selected order together with the clear-text
tokens. On Postgres the select adds `FOR UPDATE OF tasks SKIP LOCKED`
(the tasks alone: locking the joined run would make two claims of
different tasks in one run exclude each other); on SQLite the single
writer makes it atomic. `RunSummary` fields that are aggregates
(`current_nodes`, `pending_requests`) come from one grouped query, never
a per-run loop.

## Migrations

- Alembic, `athanore/store/migrations/versions/`. The first version
  creates the v1 schema.
- `athanore serve` runs `alembic upgrade head` on start (configurable
  off). `athanore db upgrade` / `db current` exist in the CLI.
- No more implicit `ALTER TABLE` in constructors.

### Importing a v0 database

`athanore db import-v0 path/to/athanore.db` (also offered automatically
when v1 opens a file that has no `alembic_version` table but does have the
MVP's `runs` table):

| v0 | v1 |
|---|---|
| `runs.id` | kept verbatim (uuid hex, not re-minted as ULID; ordering is by `position` anyway) |
| `runs.priority` | `runs.position` |
| `runs.status='running'` with no tasks ever started | `queued` |
| `tasks.token` | dropped; finished tasks get `token_hash = sha256(token)` for the record, ready tasks get NULL and are tokened at claim |
| `tasks.run_priority` | dropped (04) |
| `log` | `log_entries` (`kind` inferred: `[stats]` → `stats`, engine `attempt N failed` → `failure`) |
| `messages kind='request'` | `requests` (mode/source/kind from `data`) |
| `messages kind='answer'` | `answers` |
| legacy `permission/question/decision/reply` kinds | handled by the same rules the MVP's in-place migration used |
| `events kind='agent_progress'` | `stream_chunks` (`kind=text`, one chunk per segment; `> tool:` lines → `tool_call`) |
| `events kind='run_stats'` | `events name='agent.stats'` and `tasks.stats` on the matching task; other kinds mapped by the rename table in 03 (`transition` → `task.enqueued reason=transition`) |

The import is idempotent and copies into a fresh v1 file; the v0 file is
never modified.

## Retention

Configurable (`settings.retention`); a background task runs hourly:

- `stream_chunks` older than 14 days for finished tasks are deleted (the
  work log keeps the deliverables; the transcript is diagnostic).
- `events` older than 30 days are deleted except run-level lifecycle
  events (`run.*`), which are kept for the run's life.
- Deleting a run deletes everything (cascade).

## Transcript writes

The façade appends chunks to an in-memory buffer; the flusher writes a
batch every `stream_flush_interval` (0.4 s default, as in the MVP) as one
insert of N rows, then publishes one ephemeral `task.stream` event
carrying `{task_id, seq_from, seq_to}` on the bus (not through the
outbox: it is never stored, 03). Readers fetch
`GET /api/tasks/{id}/stream?after=<seq>`.

## Concurrency and SQLite settings

`journal_mode=WAL`, `synchronous=NORMAL` (durable across a process crash,
may lose the last transactions on power loss; acceptable for a local
tool), `busy_timeout=5000`, `foreign_keys=ON`. One writer connection
serialised by an asyncio lock in the UnitOfWork; readers use a small
pool. Long-running reads (event history) paginate.

A connection SQLAlchemy invalidates is rolled back before it is closed
(D262). A cancellation that lands inside a statement is an exit exception
to SQLAlchemy, which closes the connection without a rollback; closed with
its interrupted statement still referenced, a SQLite connection is a
zombie whose transaction — and write lock — outlive it until the cursor is
garbage-collected, and every writer after it fails at `busy_timeout`. The
rollback is a pool `invalidate` listener beside the pragmas, SQLite only.

## Backups

The database is one file plus WAL; `athanore db backup <path>` uses the
SQLite backup API for a consistent copy while running.

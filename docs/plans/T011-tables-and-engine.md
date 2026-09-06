# T011 — SQLAlchemy Core tables and the engine factory

**Task.** `docs/v1/17-serial-task-plan.md` § `### T011`.
**Specs.** `docs/v1/07-storage.md` §Schema (every table, column, index
and constraint — this task is that section, transcribed into Core);
`docs/v1/02-architecture.md` §Library choices (SQLAlchemy 2.0 **Core**,
no ORM; SQLite in WAL).

## What this task is

The schema as `Table` objects, and the async engine factory that
configures SQLite correctly. Nothing queries anything yet.

## What this task is not

- **No ORM.** No declarative base, no mapped classes, ever
  (`AGENTS.md` §Stack).
- **T012** owns Alembic and the initial migration. This task creates
  tables in tests via `metadata.create_all`; production DDL is the
  migration's job, and T012's Done says no `CREATE TABLE` lives outside
  it.
- **T013a onward** own `Store`, `UnitOfWork` and the repositories. No
  queries, no session management here.

## Steps

1. `athanore/store/tables.py`:
   - `metadata = MetaData(naming_convention=…)` — the convention matters,
     because Alembic's autogenerate comparison in T012 depends on
     constraint names being deterministic;
   - `JSONV = JSON().with_variant(JSONB, "postgresql")` and
     `TS = DateTime(timezone=True)`;
   - the tables exactly as 07 §Schema: `runs`, `tasks` (`token_hash
     String(64)` nullable, `stats JSONV` nullable, `lineage JSONV`,
     `terminal Boolean default False`, `branch JSONV default []`),
     `join_arrivals` (unique on `run_id, join_node, fanout_task, index`),
     `log_entries`, `submissions`, `stream_chunks`
     (`UniqueConstraint("task_id","seq")`), `requests`, `answers`
     (`request_id` as both PK and FK), `events` (`id Integer` PK
     autoincrement);
   - every foreign key `ondelete="CASCADE"`; every index from 07.
2. The one subtle constraint — `requests.ordinal` is nullable with a
   **partial** unique index, so many rows may have `NULL` but a given
   `(task_id, ordinal)` pair is unique:
   ```python
   Index("uq_requests_task_ordinal", "task_id", "ordinal", unique=True,
         sqlite_where=text("ordinal IS NOT NULL"),
         postgresql_where=text("ordinal IS NOT NULL"))
   ```
   Both dialect predicates are required; one alone silently degrades on
   the other backend.
3. `athanore/store/engine.py`: `make_engine(db_url) -> AsyncEngine`, and
   for SQLite a `connect` listener issuing `PRAGMA journal_mode=WAL`,
   `synchronous=NORMAL`, `busy_timeout=5000`, `foreign_keys=ON`.
   `pool_size=4`. Plus an `is_sqlite(engine)` helper.
   **`foreign_keys=ON` is not the SQLite default** — without the listener
   every FK in the schema is decorative, which is exactly what the test
   below catches.

## Verification

`tests/store/test_tables.py`, against a tmp SQLite file (not `:memory:`
— WAL and the pragmas need a real file):

- `metadata.create_all` succeeds;
- each PRAGMA reads back the value that was set;
- inserting a task with an unknown `run_id` raises `IntegrityError`,
  proving foreign keys are on;
- two requests with the same `(task_id, ordinal)` raise; two with
  `ordinal NULL` do not.

## Done

- Tests pass; pyright strict clean on `athanore/store`.
- Every table, index and constraint of 07 §Schema present — diff the
  section against the module line by line before you call it done.
- `**Status.** Done.` on `### T011`, in the same commit.

## Files

```
athanore/store/tables.py
athanore/store/engine.py
tests/store/test_tables.py
docs/v1/17-serial-task-plan.md
```

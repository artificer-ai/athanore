# T018 — v0 importer

**Task.** `docs/v1/17-serial-task-plan.md` § `### T018`.
**Specs.** `docs/v1/07-storage.md` §v0 mapping (the row-by-row table this
task implements); `docs/v1/14-migration-and-phasing.md` §Importing v0.

## Read this first: the fixture instruction is stale

The task says to build the fixture with "the **MVP** `athanore.store.Store`
(still present)". It is not present. D65 removed all MVP code from this
repository, and D67 forbids v0 and v1 sharing an environment — importing
v0's `athanore` here is exactly the collision that decision exists to
prevent.

Build the fixture with the **stdlib `sqlite3` module** instead, writing
v0's schema and rows directly. v0's schema is readable at
`$MVP_CHECKOUT/athanore/store.py` in the sibling checkout, which is
mounted in the container — read it, transcribe the `CREATE TABLE`
statements the fixture needs, and note in `docs/v1/15-decisions.md` that
the fixture is built without importing v0.

## What this task is

A committed, realistic v0 database, and the importer that turns one into
a v1 database.

## What this task is not

- No changes to v0. `import_v0` **never writes to `src`** — the test
  hashes the file before and after.
- No CLI command yet (T011's CLI surface and T054's `athanore import`
  own that); this is the function.
- No schema changes. The destination is a freshly migrated v1 database.

## Steps

1. `scripts/make_v0_fixture.py` → `tests/fixtures/v0/mvp_small.sqlite3`
   (that extension, so `.gitignore`'s `athanore.db*` rules do not
   swallow it). Contents, all of which the mapping needs exercised:
   two runs (one completed, one `running` with no task ever started),
   tasks in each status, a log with a `[stats]` line and an
   `attempt 1 failed` engine line, a `messages` request + answer pair,
   legacy `permission` and `question` kinds, `agent_progress` events
   including a `> tool:` line, a `run_stats` event, a `transition` event.
   Commit the file.
2. `athanore/store/legacy.py`: `async def import_v0(src, dest_url) ->
   ImportReport`, implementing 07's mapping row by row — `sqlite3` read
   of the source, Core inserts into the destination. The mappings that
   are easy to get wrong:
   - `runs.priority → position`;
   - a `running` run with no started task → `queued`;
   - `tasks.token → token_hash` for finished tasks, `NULL` otherwise —
     a live clear-text token must never survive the import;
   - `log → log_entries` with kind inference;
   - `messages` split into `requests` + `answers`;
   - `agent_progress → stream_chunks`;
   - `run_stats → agent.stats` event **and** `tasks.stats`;
   - `transition → task.enqueued` with `reason=transition`.
3. Idempotent: skip a run whose id already exists in the destination.

## Verification

`tests/store/test_legacy_import.py`:

- row counts per table match the fixture's expectations;
- running the import twice changes nothing (compare the full row set,
  not just counts);
- the source file's bytes are unchanged — hash before and after.

## Done

- Tests pass; the fixture is committed and small.
- A decision row for building the fixture without importing v0.
- `**Status.** Done.` on `### T018`, in the same commit.

## Files

```
scripts/make_v0_fixture.py
tests/fixtures/v0/mvp_small.sqlite3
athanore/store/legacy.py
tests/store/test_legacy_import.py
docs/v1/15-decisions.md
docs/v1/17-serial-task-plan.md
```

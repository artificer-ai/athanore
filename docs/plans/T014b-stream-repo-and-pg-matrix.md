# T014b — `StreamRepo` and the Postgres test matrix

**Task.** `docs/v1/17-serial-task-plan.md` § `### T014b`.
**Specs.** `docs/v1/07-storage.md` §Schema (`stream_chunks`, the
`(task_id, seq)` unique constraint); `docs/v1/13-testing.md` §Matrix.

## What this task is

The agent-output chunk store, and the fixture that makes **every** store
test run twice: SQLite always, Postgres when `ATHANORE_TEST_PG_URL` is
set. From here on, a query that only works on SQLite fails in CI's
nightly job rather than in production.

## What this task is not

- No streaming API and no SSE — T044.
- No retention job — T017 calls `prune_finished`.
- The parametrisation applies to `tests/store/`; do not spread the
  marker across unrelated suites.

## Steps

1. `repos/stream.py`:
   - `append_batch(task_id, chunks: list[(seq, kind, text)])` as **one**
     multi-row `INSERT … VALUES (…),(…)`. Chunks arrive in bursts; a
     per-chunk insert is a per-chunk transaction cost;
   - `list_after(task_id, after_seq, limit)`;
   - `last_seq(task_id)`;
   - `prune_finished(before)` joining `tasks` on `finished < before`.
2. `tests/store/conftest.py`: a `db_url` fixture parametrised over
   SQLite (always) and `ATHANORE_TEST_PG_URL` (marked `postgres`,
   skipped when unset), applied to every store test — including the ones
   T011–T014a already wrote. Retrofitting them is part of this task.

## Verification

```sh
./scripts/dev.sh "uv run pytest -q tests/store"                 # SQLite only
docker compose --profile pg up -d postgres
./scripts/dev.sh "uv run pytest -q -m postgres tests/store"     # both backends
```

Both must pass, and without the `pg` profile the Postgres variants must
**skip**, not error. Specifically test: a batch insert of 50 chunks;
`list_after` pagination; a duplicate `(task_id, seq)` raising; and
`prune_finished` leaving running tasks alone.

## Done

- Store suite green on SQLite; green on Postgres with the profile up;
  skipped cleanly without it.
- Every existing store test now runs under the parametrised fixture.
- `**Status.** Done.` on `### T014b`, in the same commit.

## Files

```
athanore/store/repos/stream.py
tests/store/conftest.py
tests/store/test_stream_repo.py
docs/v1/17-serial-task-plan.md
```

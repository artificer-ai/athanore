# T015 — `TaskRepo`

**Task.** `docs/v1/17-serial-task-plan.md` § `### T015`.
**Specs.** `docs/v1/07-storage.md` §Schema (`tasks`);
`docs/v1/04-engine.md` §Attempts and §Recovery;
`docs/v1/12-security.md` §Task tokens.

## What this task is

Everything the engine will need to read and write about a task, except
claiming — which is T015a, deliberately separate because it is the one
query with concurrency semantics.

## What this task is not

- **No `claim_ready`.** That is T015a.
- No scheduler, no dispatch, no retry policy. This repo records
  outcomes; who decides them is the engine's business (T032+).
- No token minting here — also T015a's, since a token exists only for a
  claimed attempt.

## Steps

Methods exactly as the task lists: `enqueue(...)` (with `created`
defaulting to now, and **retries passing the original `created`** so a
retried task does not jump the queue), `get`, `list_for_run`,
`by_token_hash`, `finish(id, status, result=None, error=None,
terminal=False)` setting `finished`, `set_status`, `set_stats`,
`last_for_node` (the payload and branch a rerun needs),
`has_pending(run_id)` (`ready`, `in_progress` or `waiting`),
`terminal_tasks(run_id)` in branch order, and `reset_for_recovery()`
flipping `in_progress|waiting → ready`, clearing `started` and
`token_hash`.

`reset_for_recovery` is the one to write carefully: it runs at startup
after a crash, it must touch **only** those two statuses, and it must
clear the token hash so a token minted for a dead attempt can never
authenticate against the new one.

## Verification

`tests/store/test_tasks_repo.py`:

- enqueue defaults (`created` now; retry keeps the old value);
- `finish` sets `finished` and `terminal`;
- `reset_for_recovery` touches only `in_progress` and `waiting`, leaves
  `done`/`failed`/`dead_letter` alone, and clears `token_hash`;
- `terminal_tasks` ordering by branch index path;
- `by_token_hash` misses for an unknown hash rather than raising.

Runs under T014b's SQLite+Postgres fixture.

## Done

- Tests pass on both backends; pyright strict clean.
- `**Status.** Done.` on `### T015`, in the same commit.

## Files

```
athanore/store/repos/tasks.py
tests/store/test_tasks_repo.py
docs/v1/17-serial-task-plan.md
```

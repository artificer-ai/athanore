# T017 — Retention job

**Task.** `docs/v1/17-serial-task-plan.md` § `### T017`.
**Specs.** `docs/v1/07-storage.md` §Retention; `docs/v1/02-architecture.md`
§Configuration (`retention.events_days=30`, `stream_days=14`).

## What this task is

The periodic prune, built on the `prune` queries T014a and T014b already
wrote. Two functions: one pass, and a cancellable loop.

## What this task is not

- No new queries. If a prune needs SQL that does not exist, it belongs
  in the repository, not here.
- Nothing starts the loop yet — T031's server does.
- Retention windows are settings, not constants. Read them from
  `Retention`; do not hard-code 14 and 30.

## Steps

1. `async def prune_once(store, retention, now)`:
   - stream chunks of **finished** tasks older than `stream_days`;
   - events older than `events_days` **except** `run.*` — a run's own
     history outlives its noise, which is what makes an old run still
     readable.
2. `async def retention_loop(store, retention, interval=3600)` —
   cancellable: `asyncio.CancelledError` must propagate cleanly, so
   shutdown does not hang for an hour.

## Verification

`tests/store/test_retention.py`, with `freezegun` so ages are exact
rather than approximate:

- chunks of a task finished 15 days ago are gone; chunks of a **running**
  task of the same age remain;
- a `task.done` event 31 days old is gone; a `run.created` of the same
  age remains;
- deleting a run removes rows from all eight child tables (the cascade
  T011 declared, asserted end to end here);
- cancelling `retention_loop` returns promptly.

## Done

- Tests pass; the loop cancels cleanly.
- `**Status.** Done.` on `### T017`, in the same commit.

## Files

```
athanore/store/retention.py
tests/store/test_retention.py
docs/v1/17-serial-task-plan.md
```

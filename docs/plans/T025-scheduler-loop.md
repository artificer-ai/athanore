# T025 — Scheduler loop

**Task.** `docs/v1/17-serial-task-plan.md` § `### T025`.
**Specs.** `docs/v1/04-engine.md` §The loop (the sequence, step by step)
and §Dispatch order.

## What this task is

The dispatch loop: reap, drain re-admits, claim what fits, spawn
attempts, sleep until woken. Everything it uses already exists — pools
(T022), `claim_ready` (T015a), `run_attempt` (T024).

## What this task is not

- No claiming logic. `claim_ready` is the query; do not re-order tasks
  here.
- No recovery (T027a) and no operator ops (T027b) beyond exposing
  `cancel_attempts(task_ids)` for them to call.
- Not a place to swallow bugs silently: an exception inside the loop is
  **logged** and the loop continues — but it is logged, every time.

## Steps

1. `class Scheduler(engine)` with `_wake = asyncio.Event()`,
   `_attempts: dict[task_id, asyncio.Task]`, `notify()`, `start()`,
   `stop()` (cancel every attempt, await them, then cancel the loop).
2. `_loop()` per 04 §The loop: reap finished attempts; then per pool —
   `drain_readmits()` first, then `free = pool.free()`, and if `free > 0`
   one uow `claim_ready(free, workflows_of(pool))` (emitting
   `run.started` for the flagged runs); for each claimed task
   `lease = pool.try_acquire()` and
   `asyncio.create_task(run_attempt(...))`.
   Re-admits before fresh claims is the ordering that keeps waiting work
   from starving (T022).
3. Wait on `_wake` with a 1 s timeout; make the tick injectable so tests
   do not sleep.
4. `cancel_attempts(task_ids)` for T027b.

## Verification

`tests/engine/test_scheduler.py`:

- with `workers=1`, two ready tasks run one after the other, not
  concurrently;
- a `capacity=0` pool never claims;
- `notify()` wakes the loop before the tick elapses — assert on timing
  with a short tick, so a broken `notify` shows up as a slow test rather
  than a passing one;
- `stop()` cancels a running body and returns.

## Done

- Tests pass; no test sleeps for a real second.
- `**Status.** Done.` on `### T025`, in the same commit.

## Files

```
athanore/engine/scheduler.py
tests/engine/test_scheduler.py
docs/v1/17-serial-task-plan.md
```

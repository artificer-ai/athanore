# T026 — Lease release for waiting bodies

**Task.** `docs/v1/17-serial-task-plan.md` § `### T026`.
**Specs.** `docs/v1/04-engine.md` §Waiting (the whole section — this task
is its implementation).

## What this task is

The mechanism that makes a one-worker install usable: a body that is
waiting on a human gives its pool slot back, and takes it again when the
answer arrives. T023 stubbed `LeaseService.released()`; this fills it in.

## What this task is not

- **No `human_input`.** T033 builds that on top of this. Tests here call
  the service directly.
- No changes to pool ordering — T022 already put re-admits ahead of
  fresh claims.
- Not a general "pause my task" API. It is scoped to waiting on a
  request.

## Steps

1. On enter: one uow — `set_status(task, waiting)` and `task.waiting
   {request_id}` (the caller passes the request id); record
   `ctx._released_at = loop.time()`; `lease.release()`;
   `scheduler.notify()`.
2. On exit: `lease = await pool.request_readmit(task_id)` — the
   scheduler hands it over in `drain_readmits` — then one uow
   `set_status(task, in_progress)` and `task.resumed`.
3. **Reschedule the node timeout.** If `ctx._timeout` is set:
   `remaining = ctx._timeout.when() - ctx._released_at`, then
   `ctx._timeout.reschedule(loop.time() + remaining)`. Without this, a
   node with `timeout=300` that waits an hour for a human fails the
   moment it resumes — the bug this step exists to prevent.
4. Store the new lease on the context, so T024's `finally` releases the
   lease the task actually holds rather than the one it started with.

## Verification

`tests/engine/test_waiting.py`:

- under `workers=1`, a body inside `released()` lets a second ready task
  run;
- the waiter re-acquires **before** a third ready task gets the slot;
- `timeout=0.2` with a `released()` lasting 0.5 s does **not** fail —
  the rescheduling test, and the reason this task exists;
- the released and re-acquired lease is the one released in `finally`
  (assert `free()` returns to capacity at the end).

## Done

- Tests pass; pool capacity accounting is exact at the end of each test.
- `**Status.** Done.` on `### T026`, in the same commit.

## Files

```
athanore/engine/services.py
tests/engine/test_waiting.py
docs/v1/17-serial-task-plan.md
```

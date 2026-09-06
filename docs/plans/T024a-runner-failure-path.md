# T024a — Runner: failure path, retries, timeouts, cancellation

**Task.** `docs/v1/17-serial-task-plan.md` § `### T024a` (the *runner*
one — a superseded duplicate of this id was deleted under D70).
**Specs.** `docs/v1/04-engine.md` §Failure policy and §Retries;
`docs/v1/15-decisions.md` D42 (what is retryable), D52, D60 (timeouts).

## What this task is

Rule 3, implemented: the `except` arm of `run_attempt`. Retry, or
dead-letter and fail the run — and never confuse a cancellation for
either.

## What this task is not

- No new failure classes. T021 wrote `NonRetryable` and `is_retryable`;
  use them rather than re-deciding what is retryable here.
- No operator ops (T027b). Cancellation *policy* is theirs; this task
  only refuses to overwrite what they recorded.
- Retries belong to the engine, not to node bodies or agent calls
  (`AGENTS.md` §Architecture rules).

## Steps

1. The `except` arm: uow `finish(failed, error=repr(exc))` and
   `log.append(engine, kind=failure, f"attempt {n} failed: {exc}")`.
2. If `is_retryable(exc)` and `attempt < (node.retries or
   settings.max_retries)`: enqueue the retry with the **same** payload,
   priority, branch and `created` (so a retry does not jump the queue —
   T015a's ordering test depends on it), `attempt + 1`, lineage
   `retry`; emit `task.failed will_retry=true retry_task_id=…`.
3. Otherwise: `set_status(task, dead_letter)`, `task.dead_lettered`,
   `set_status(run, failed)`, `run.failed`.
4. `asyncio.TimeoutError` from the node timeout takes the same arm — a
   timeout is retryable (D42).
5. `CancelledError`: **re-raise without writing a status.** The operator
   op has already recorded `cancelled`, and a shutdown deliberately
   leaves the row `in_progress` for recovery to find. Writing a status
   here is how a graceful restart turns into lost work.
6. T024's `finally` still runs on every path.

## Verification

`tests/engine/test_runner_failures.py`:

- a raising body retries, keeping `created` and incrementing `attempt`;
- `NonRetryable` and `GraphError` dead-letter on attempt 1 and fail the
  run;
- the third failure of a `retries=3` node dead-letters;
- `timeout=0.05` against a sleeping body → failed, then retried;
- cancelling the asyncio task leaves the row `in_progress` and records
  nothing — assert the row is untouched, not merely that no exception
  escaped;
- the failure log line exists with `kind=failure`.

## Done

- Tests pass, including the cancellation one.
- `**Status.** Done.` on `### T024a`, in the same commit.

## Files

```
athanore/engine/runner.py
tests/engine/test_runner_failures.py
docs/v1/17-serial-task-plan.md
```

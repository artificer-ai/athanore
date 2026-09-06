# T027b — Operator ops, part 2: cancel, delete, rerun, retry, move, set_status

**Task.** `docs/v1/17-serial-task-plan.md` § `### T027b`.
**Specs.** `docs/v1/04-engine.md` §Operator operations;
`docs/v1/07-storage.md` §Cascades; T024c's two join rules.
**Reference.** v0's `tests/test_management.py` (engine parts).

## What this task is

The destructive and re-dispatching verbs. Two things need care: killing
a running attempt happens **after** the transaction commits, and lineage
plus `created` rules decide whether re-dispatched work jumps the queue.

## What this task is not

- No API. T044a re-adds the HTTP-level assertions.
- No new join mechanism — T024b/T024c own it; honour their two rules.

## Steps

- `cancel(run)`: collect `ready|in_progress|waiting` task ids, mark them
  `cancelled` in the uow (`task.cancelled reason=cancel`), run
  `cancelled`; **then**, after commit, `scheduler.cancel_attempts(ids)`.
  Cancelling the asyncio task first would race the transaction and let
  T024a's `CancelledError` arm see a row that is not yet cancelled.
- `delete(run)`: `cancel`, then `runs.delete` and `run.deleted`,
  relying on the cascades.
- `rerun(run, node)`: payload and branch from `last_for_node`, lineage
  `rerun`, attempt = max attempt for that node + 1; a **join** node
  replays its stored arrivals payload.
- `retry(task)`: lineage `manual_retry`, **keeps `created`**, copies
  branch.
- `move(task, node)`: `Conflict` for a join target; cancel the task
  (killing the attempt via `cancel_attempts`), enqueue at the target
  with the same payload and branch, lineage `move`, **fresh `created`**.
  Retry keeps its place in the queue; a move is new work and goes to the
  back — that asymmetry is deliberate, test both.
- `set_status(task, ready | cancelled | dead_letter)`.
- Re-opening a terminal run sets `running` and emits `run.updated
  {changed: {status}}`.

## Verification

`tests/engine/test_ops_tasks.py`:

- cancel kills a sleeping body and marks every affected task;
- delete leaves no child rows in **any** of the nine tables — assert per
  table, not just on `runs`;
- rerun / retry / move lineage and `created` rules, including the
  keeps-vs-fresh asymmetry;
- `set_status(ready)` re-dispatches;
- move into a join → `Conflict`;
- a terminal run re-opens on retry.

## Done

- Tests pass.
- Ledger rows for `test_management.py`, `test_pause.py`,
  `test_run_log.py` ticked (API halves noted as T044a's).
- `**Status.** Done.` on `### T027b`, in the same commit.

## Files

```
athanore/engine/ops.py
tests/engine/test_ops_tasks.py
docs/porting-ledger.md
docs/v1/17-serial-task-plan.md
```

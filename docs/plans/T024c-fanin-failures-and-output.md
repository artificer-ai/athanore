# T024c — Fan-in: failure semantics, late arrivals, output shape

**Task.** `docs/v1/17-serial-task-plan.md` § `### T024c`.
**Specs.** `docs/v1/04-engine.md` §Completion and §Output shape;
`docs/v1/15-decisions.md` D58, D62.

## What this task is

What happens when a fan-out does **not** all arrive, and what a run's
`output` is once branches exist. The determinism requirement is the
point: the same graph with different body timings must produce the same
`output`.

## What this task is not

- No new join mechanism — T024b built it.
- No API surface. `Ops` is T027b; this task only states the two rules it
  must honour (`move` into a join is a `Conflict`; `rerun` of a join
  replays the stored payload) so T027b implements them.

## Steps

1. Completion check in the runner: no pending tasks **and**
   `JoinRepo.incomplete(run)` empty → `completed`, with `output` per the
   shape rule (a single terminal task → its value; several → a list in
   **branch order**, never finish order). Non-empty → `failed` with
   `join_incomplete: <join> has k of n arrivals` and `run.failed
   code=join_incomplete`.
2. Late arrivals — after the join task exists — are stored with
   `late=true` and emit `join.arrived late=true`, and do **not** create a
   second join task.
3. The two `Ops` rules T027b must implement: `move` rejects a join
   target with `Conflict`; `rerun` of a join node replays the stored
   payload rather than recomputing arrivals.

## Verification

`tests/engine/test_fanin_failures.py`:

- one branch dead-letters → run `failed`; `retry` on it → the join fires
  → run `completed`;
- a branch that terminates instead of joining → `failed` with
  `code=join_incomplete`;
- a late arrival after the join fired → `late: true`, and no second join
  task;
- recovery with two of three arrived → the third arrives after a restart
  and the join fires;
- `output` is a scalar with a join and a list without one;
- **the same fan-out with shuffled body delays yields an identical
  `output`** — run it several times with different sleeps; this is the
  task's Done condition, not an optional extra.

## Done

- Tests pass; no `output` assertion depends on finish order.
- `**Status.** Done.` on `### T024c`, in the same commit.

## Files

```
athanore/engine/runner.py
tests/engine/test_fanin_failures.py
docs/v1/17-serial-task-plan.md
```

# T024b — Fan-in: branch frames, `JoinRepo`, arrival and dispatch

**Task.** `docs/v1/17-serial-task-plan.md` § `### T024b`.
**Specs.** `docs/v1/04-engine.md` §Fan-out and fan-in;
`docs/v1/15-decisions.md` D62; `docs/v1/18-event-payloads.md`
(`join.arrived`).

## What this task is

Fan-out that remembers where it came from, and a join that fires exactly
once when every branch has arrived. The branch stack is the whole
mechanism: each fan-out pushes a frame, each join pops one.

## What this task is not

- **T024c** owns failure semantics, late arrivals and the run's `output`
  shape. Stop at "the join fires".
- No new rule. A join is node metadata (`join=True`) — an existing seam,
  not a fourth rule (`AGENTS.md`).
- No operator ops. T024c handles `move`/`rerun` against joins.

## Steps

1. `TaskRepo.enqueue` propagates `branch`: copied from the parent for
   single transitions, retries, reruns and moves; a **pushed frame** for
   fan-outs. A list of N ≥ 1 transitions pushes
   `{fanout: task.id, index: i, count: N, key: jsonable(payload)}` onto
   each child.
2. `store/repos/joins.py`:
   - `arrive(run_id, join_node, fanout_task, index, key, value,
     from_task) -> (arrived, count, late)` — an upsert on T011's unique
     key, with `late=True` when a join task for that fan-out already
     exists;
   - `arrivals(run_id, join_node, fanout_task)`;
   - `incomplete(run_id) -> list[(join_node, fanout_task, arrived,
     count)]`.
   The upsert is what makes a duplicated arrival (a retried branch)
   harmless.
3. Runner: a transition whose target has `join=True` pops the top frame
   (`GraphError` on an empty stack), calls `arrive`, emits
   `join.arrived`, and when `arrived == count` enqueues the join task
   with `payload = [{index, key, value, from_task}]` **in index order**,
   `branch = frames[:-1]`, lineage `{from: fanout, reason: "join",
   arrivals: [...]}`.
4. Graph builder: `node(join=True)`; `finalize` rejects a join with no
   payload slot (a join that cannot receive its arrivals is a typo, not
   a graph).

## Verification

`tests/engine/test_fanin.py`:

- three branches → the join receives three dicts **in index order**,
  carrying the fan-out keys;
- nested fan-out/join;
- `count == 1` fires on the first arrival;
- routing into a join with no frame raises `GraphError`;
- a join node without a payload slot fails `finalize`;
- the join task's `branch` is the parent's stack minus the popped frame.

## Done

- Tests pass on SQLite and Postgres (the upsert differs by dialect —
  run both).
- `**Status.** Done.` on `### T024b`, in the same commit.

## Files

```
athanore/store/repos/joins.py
athanore/store/repos/tasks.py     (branch propagation)
athanore/engine/runner.py
athanore/graph/{builder.py,validate.py}
tests/engine/test_fanin.py
docs/v1/17-serial-task-plan.md
```

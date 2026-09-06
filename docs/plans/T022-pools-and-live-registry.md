# T022 — Pools, leases, re-admit queue, live registry

**Task.** `docs/v1/17-serial-task-plan.md` § `### T022`.
**Specs.** `docs/v1/04-engine.md` §Pools and §Waiting (why a waiting task
gives its slot back and has to queue to get it again);
`docs/v1/15-decisions.md` D43.

## What this task is

Capacity accounting, and the registry of in-flight contexts. The
re-admit queue is the subtle part: a task that awaited a human and got
its answer must reclaim a slot **ahead of** fresh work, or a busy pool
starves everything that is already half-done.

## What this task is not

- No dispatch loop — T032. Nothing here claims tasks or runs bodies.
- `Pool` is **public API** (users write `Pool("sandbox", capacity=1)`),
  so it is frozen and validates its name `^[a-z][a-z0-9_]*$`.
- No fairness heuristics beyond FIFO. Do not invent priorities inside a
  pool.

## Steps

1. `engine/pools.py`:
   - `class Pool(name, capacity)` — public, frozen, name-validated;
   - `class PoolState(pool)` with `leased: int` and
     `readmit: deque[Waiter]`, `Waiter = (task_id, future[Lease],
     enqueued_at)`;
   - `free()`, `try_acquire() -> Lease | None`, `release(lease)`,
     `request_readmit(task_id) -> Awaitable[Lease]`,
     `drain_readmits()` handing leases while `free() > 0`;
   - `class Lease(pool_state, task_id)` with an **idempotent**
     `release()` — double release must not manufacture capacity.
2. `class PoolRegistry`: `add`, `bind(workflow, pool_name)`,
   `for_workflow`, `workflows_of`, `snapshot() -> dict[name,
   {capacity, in_flight}]`; rejects a duplicate pool name and a pool
   name equal to a workflow name.
3. `engine/live.py`: `class LiveRegistry` — `register(ctx)`,
   `unregister(task_id)`, `context_for(task_id)`, `all()`.

## Verification

`tests/engine/test_pools.py`:

- capacity 0 never acquires;
- release then acquire succeeds;
- `drain_readmits` serves a re-admit **before** a fresh `try_acquire`;
- FIFO among re-admits;
- double `release()` on one lease does not raise `free()` above capacity.

## Done

- Tests pass; pyright clean.
- `**Status.** Done.` on `### T022`, in the same commit.

## Files

```
athanore/engine/pools.py
athanore/engine/live.py
tests/engine/test_pools.py
docs/v1/17-serial-task-plan.md
```

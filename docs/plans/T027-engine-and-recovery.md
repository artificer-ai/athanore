# T027 — `Engine` object and recovery

**Task.** `docs/v1/17-serial-task-plan.md` § `### T027`.
**Specs.** `docs/v1/04-engine.md` §Recovery and §Shutdown;
`docs/v1/03-domain-model.md` §Run lifecycle.

## What this task is

The object that owns everything the engine has: pools, graphs, the live
registry, the scheduler, ops. Plus the two lifecycle paths that matter
most in practice — what happens at startup after a crash, and what
happens on the way down.

## What this task is not

- **T027a/T027b** implement `Ops`. This task declares the attribute and
  the exception types they raise.
- No API. `UnknownWorkflow`, `NotFound`, `Conflict` are engine
  exceptions; mapping them to HTTP codes is T030's.
- Recovery does not re-run anything itself; it makes rows claimable
  again and lets the scheduler do its job.

## Steps

1. `athanore/engine/__init__.py`: `class Engine(settings, store, bus)`
   with `pools: PoolRegistry`, `graphs: dict[str, Graph]`, `live`,
   `scheduler`, `ops`, and `register(graph, pool)`.
   - `async start()`: recovery **then** the scheduler. In that order —
     starting the loop first lets it claim rows that recovery is about
     to rewrite.
   - `async stop()` per 04 §Shutdown: stop claiming, emit
     `engine.stopping`, cancel attempts, wait ≤ 10 s.
2. `athanore/engine/recovery.py`: `recover(engine)` — one uow calling
   `reset_for_recovery()` and emitting `engine.recovered {task_ids}`.
   **Runs of unregistered workflows are left alone**: their rows stay as
   they are and are never claimed, and the API flags them from
   `engine.graphs`. Silently resetting them would make a run of a
   workflow nobody has registered look ready forever.
3. `engine/errors.py` gains `UnknownWorkflow`, `UnknownNode`,
   `NotFound`, `Conflict(message)`.

## Verification

`tests/engine/test_recovery.py`:

- `in_progress` and `waiting` rows become `ready` with a NULL token
  hash — the stale token must not survive;
- `engine.recovered` lists exactly those task ids;
- a run of an unregistered workflow is untouched and never claimed.

`tests/engine/test_shutdown.py`:

- `stop()` during a sleeping body emits `engine.stopping`, leaves the row
  `in_progress` (T024a's cancellation rule), and a following `start()`
  recovers it. Assert the round trip, not the two halves separately.

## Done

- Both suites pass.
- `**Status.** Done.` on `### T027`, in the same commit.

## Files

```
athanore/engine/__init__.py
athanore/engine/recovery.py
athanore/engine/errors.py
tests/engine/{test_recovery.py,test_shutdown.py}
docs/v1/17-serial-task-plan.md
```

# T083 — Engine: replace, unregister, recovery by name

**Task.** `docs/v1/17-serial-task-plan.md` § `### T083`.
**Specs.** `docs/v1/22-live-registration.md` §Effects (Add, Replace,
Remove — the engine steps of each), §Pools; `docs/v1/04-engine.md`
§Pools, §Dispatch order, §Shutdown, §Recovery on startup (the rules
this task makes callable at runtime); D42 (a vanished node
dead-letters), D52 (no status written on interruption), D221 (remove
cancels and refuses nothing).

## What this task is

The engine tier's half of live registration, and nothing above it: the
graph registry, the pool registry, the scheduler's attempts, and
recovery, all made operable after `start()`. No server verb, no route,
no event name is added here — T085 emits `workflow.*` around the calls
this task provides.

1. **`PoolRegistry.unbind(workflow)`** (`athanore/engine/pools.py`):
   drop the binding; `KeyError` if unbound. The pool stays. After it,
   `workflows_of(pool)` no longer lists the name and `for_workflow`
   raises as for any unbound name.
2. **`PoolRegistry.rebind(workflow, pool_name)`**: move a binding to
   another existing pool. It does not check what is in flight — that is
   the engine's to know (step 4).
3. **`Engine.replace(graph, pool=None)`** (`athanore/engine/__init__.py`):
   the name must be registered (`KeyError` otherwise). `pool is None`
   keeps the binding. A `pool` naming the bound pool is a no-op on the
   binding; a different one is refused with `ValueError` while any
   attempt of the workflow is in flight (step 4's predicate), and
   `rebind`s otherwise. The pool must exist already (`KeyError` from
   the registry's own check — `add` is not called here; capacity is the
   host's, 22 §Pools). Then `self.graphs[name] = graph`. The order —
   refuse, then bind, then swap — leaves the engine untouched on any
   refusal.
4. **`Engine.attempts_of(workflow) -> list[int]`**: the task ids in
   `scheduler.in_flight` whose run is of `workflow`. The scheduler knows
   task ids, not workflows; the runner knows both when it claims. The
   cheapest honest source is the `LiveRegistry` (`engine/live.py`): a
   `LiveContext` carries its run's workflow — confirm, and add the field
   if it does not. Waiting attempts (parked on `human_input`) are live
   contexts too, so they are included, which 22 §Remove requires.
5. **`await Engine.unregister(name) -> list[int]`**: `attempts_of(name)`
   → `scheduler.cancel_attempts(ids)` → **await those attempts' asyncio
   tasks** (gather, `return_exceptions=True`; the runner's `finally`
   gives the slot back, flushes the transcript and records the stats
   entry — the façade's own cancellation path, 05 §Session lifecycle
   step 7). Then `del self.graphs[name]`, `pools.unbind(name)`. Return
   the ids that were live. Nothing writes a task status: the rows stay
   as 04 §Shutdown leaves them (D52), and the run row is not touched.
   The scheduler needs a way to await specific attempts — add
   `Scheduler.wait_for(task_ids)` beside `cancel_attempts` rather than
   reaching into `_attempts` from the engine.
6. **`recover(engine, workflows=None)`** (`athanore/engine/recovery.py`):
   the existing function takes an optional list of names; `None` keeps
   today's "every registered workflow". Same transaction shape, same
   `engine.recovered {task_ids}`, nothing emitted when nothing was
   reset. It is already safe to call after start — assert that in a
   test rather than assume it, since the reset must not touch a row an
   attempt in this process holds; at an `add` there are none (22 §Add
   step 3), and this task does not call it from `replace`.
7. **Runner and ops unchanged.** `runner._load_graph` reads
   `engine.graphs` by name at claim; `_load_node` raises `GraphError`
   for a missing node and dead-letters; `ops.submit` reads
   `engine.graphs`. Add the assertions, change no code.
8. **Fold into 04.** §Pools gains the unbind/rebind sentence and the
   "no move with attempts in flight" rule; a new paragraph after
   §Recovery on startup, *Live registration*, states that the same
   reset runs for one name when it is added to a running server and
   points at 22 §Effects.

## What this task is not

- No `Server` change, no `workflow.*` event, no `load_target`, no route,
  no CLI. `Server.register` still refuses a duplicate and still works
  only the way it does today.
- No change to the plugin host; a replaced graph's plugin spec is
  T084's problem and the server's to sequence (T085).
- No new stats reason: a cancelled attempt records `reason=shutdown`
  exactly as the façade does for any `CancelledError` today (05 §Stats
  entry). The audit trail for *why* is T085's `workflow.unregistered`.
- No change to `reset_for_recovery`'s SQL: it already filters by
  workflow.
- Snapshot untouched.

## Tests

`tests/engine/`, on the engine fixture with `MockAgent` bodies unless a
subprocess is the point:

- `test_pools.py`: `unbind` drops the binding and keeps the pool;
  `workflows_of` follows; `rebind` moves; both raise for unknown names.
- `test_replace.py` (new): two graphs under one name whose bodies leave
  distinguishable marks; start a run, let the first node claim, then
  `replace`; the in-flight attempt finishes with the *old* body's mark
  and the next task dispatches the *new* body's; a replacement lacking
  the next node dead-letters that task with `GraphError` in the failure
  entry; `replace` with a different pool raises `ValueError` while an
  attempt is live and rebinds once it is done; `replace` on an
  unregistered name raises `KeyError`; a refusal leaves `graphs` and the
  binding as they were.
- `test_unregister.py` (new): with a `FakeACPAgent` body mid-turn,
  `unregister` returns the attempt's id, the subprocess has a
  `returncode`, the transcript is flushed, a stats entry exists, the
  task row is still `in_progress`, the run row is still `running`,
  `graphs` lacks the name, `workflows_of(pool)` lacks it, the pool is
  still registered; a `waiting` attempt (a `human_input` body) is
  cancelled too; ready tasks of the workflow are never claimed
  afterwards (tick, assert still `ready`); `unregister` on an unknown
  name raises `KeyError`.
- `test_recovery.py`: after an `unregister`, `register` the name again
  and `recover(engine, [name])` resets exactly that workflow's rows,
  emits `engine.recovered` with their ids, and leaves another
  workflow's `in_progress` row (held by a live attempt) alone;
  `recover(engine, [name])` with nothing to reset emits nothing.
- `test_runner.py` / `test_ops_basic.py`: one assertion each that the
  graph is read from `engine.graphs` at claim / submit time (swap the
  dict entry between two calls).

## Verification

```sh
./scripts/test.sh -k "pools or replace or unregister or recovery or runner or ops_basic"
./scripts/test.sh
git diff --exit-code tests/snapshots
```

## Done

- `Engine.replace`, `Engine.unregister`, `Engine.attempts_of`,
  `PoolRegistry.unbind`/`rebind`, `recover(engine, workflows)` exist
  with the semantics above; runner and ops untouched and asserted; 04
  folded; gate green; snapshot unchanged.

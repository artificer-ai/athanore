# T083 — Engine: replace, unregister, recovery by name

**Task.** `docs/v1/17-serial-task-plan.md` § `### T083`.
**Specs.** `docs/v1/22-live-registration.md` §Effects (Add step 3,
Replace step 1 and the two bold paragraphs, Remove steps 1–2), §Pools,
§Testing (the *Engine* bullet); `docs/v1/04-engine.md` §Pools,
§Dispatch order, §The loop, §Shutdown, §Recovery on startup; D42 (a
vanished node dead-letters), D52 (no status written on interruption),
D221 (remove cancels the way shutdown does and refuses nothing), D223
(a live registration's pool is the one it names).

## What this task is

The engine tier's half of live registration, and nothing above it: the
graph registry, the pool registry, the scheduler's attempts and
recovery, all made operable after `start()`. No server verb, no route,
no event name is added here — T085 sequences and announces the calls
this task provides.

Two facts about the code decide the shape of everything below, so the
implementer should hold them before writing a line:

- **The scheduler is the only object that knows every attempt from the
  moment it is spawned.** The live registry (`engine/live.py`) learns of
  an attempt only when the runner binds its context, which is *after*
  `_load_run`'s await (`runner.py:165–196`). An attempt spawned by a
  claim and still inside that await is invisible to the registry, so
  "every attempt of this workflow" cannot be answered from it. It is
  answered from the scheduler, which is given the workflow at spawn.
- **A claim is an await inside a tick.** `_dispatch_pool` reads
  `workflows_of(pool)` and then awaits `_claim`; anything the engine
  does to the registries between those two points is invisible to that
  claim. Every mutation that must be exact with respect to what is in
  flight therefore runs *between ticks*, under one scheduler primitive
  (`quiescent()`, step 4), rather than reasoning about windows.

### The store

1. **`ClaimedTask` gains `workflow: str`** (`athanore/store/repos/tasks.py`).
   `claim_ready` already flips the claimed runs in `_start_runs` over
   their ids; add one `select(runs.c.id, runs.c.workflow)` over the
   distinct run ids of the won rows (or read it off the re-select by
   joining `runs`) and fill the field. It is the fourth NamedTuple
   field, required, in that position; `tests/store/test_claim.py:541`
   constructs one by hand and gains the argument. `test_claim.py`
   asserts the field is the run's `workflow` for a claim over two
   workflows.
2. **`reset_for_recovery(workflows=None, *, exclude: Sequence[int] = ())`**:
   the ids in `exclude` are never touched (`tasks.c.id.notin_(...)`,
   added only when `exclude` is non-empty). This is what lets a
   runtime recovery leave alone a row an attempt of *this* process
   holds (step 8). `tests/store/test_tasks_repo.py` gains one test: two
   interrupted rows, one excluded, one reset.

### The pool registry (`athanore/engine/pools.py`)

3. **`PoolRegistry.unbind(workflow) -> None`**: drop the binding.
   `KeyError` if the name is not bound (the registry's lookup error,
   as `for_workflow` raises). The pool stays. Afterwards
   `workflows_of(pool)` no longer lists the name and `for_workflow`
   raises for it. **`PoolRegistry.rebind(workflow, pool_name) -> PoolState`**:
   move a bound name to another registered pool; `KeyError` for an
   unbound workflow or an unknown pool (both are lookups — `bind`'s
   `ValueError` is for a *registration* that is wrong, and T085 needs
   to tell "unknown pool" from the in-flight refusal by type); the same
   pool is a no-op. Neither checks what is in flight: that is the
   engine's to know, and the class docstring's "moving a workflow would
   strand the tasks already leased" sentence is amended to say that
   `bind` refuses a move and `rebind` performs one for the engine,
   which checks first.

### The scheduler (`athanore/engine/scheduler.py`)

4. **`_Attempt` gains `workflow: str`**, filled in `_spawn` from
   `claimed.workflow`. **`Scheduler.attempts_of(workflow) -> list[int]`**:
   the task ids of the attempts in `_live` of that workflow that are not
   `done()`, in spawn order, each id once (a re-dispatched row has two
   attempts and one id). A `waiting` attempt is an attempt (its task is
   parked inside `released()`, not ended), so it is listed — 22
   §Remove step 1 requires it.
5. **`Scheduler.wait_for(task_ids) -> None`**: `gather` every attempt in
   `_live` whose task id is in `task_ids`, `return_exceptions=True`,
   then `_reap()` so their slots are back and `in_flight` no longer
   lists them — the tail of `_cancel_all`, for a chosen set. Ids
   nothing is running are skipped. Does not cancel: the caller already
   did, with `cancel_attempts`.
6. **`Scheduler.quiescent()`**: an `asynccontextmanager` over a new
   `asyncio.Lock` that `_loop` holds around each `_dispatch_all()`.
   Inside the block no tick is in progress and none starts; the tick in
   progress at entry finishes first, and every attempt a claim before
   now produced has been spawned (spawning is synchronous within the
   tick). Free when the loop is not running, so it costs nothing before
   `start()` and after `stop()`. **Not reentrant** — nothing inside a
   block may await something that takes it — and the block is short:
   registry mutations and one store transaction at most, never a wait
   on an attempt. `_wait` stays outside the lock, so `notify()` from a
   cancelled attempt's `finally` wakes the loop as it does today.

### The engine (`athanore/engine/__init__.py`)

7. **`Engine.attempts_of(workflow) -> list[int]`**: `self.scheduler.attempts_of`.

   **`await Engine.replace(graph, pool: str | Pool | None = None) -> None`**:
   `KeyError` if `graph.name` is not registered. `pool is None`: swap
   the graph, done. Otherwise only the *name* of `pool` is read — a
   `Pool` object's capacity is ignored, because creating or resizing a
   pool is not a registration's to do (22 §Scope, §Pools) — and:
   under `quiescent()`, if the name differs from the current binding,
   `KeyError` when it is not a registered pool (check first: a typo is
   reported as a typo), `ValueError` naming the workflow, both pools and
   the ids when `attempts_of(name)` is non-empty, else
   `pools.rebind(name, pool_name)`; then `self.graphs[name] = graph`.
   Refuse, then bind, then swap: a refusal leaves the engine untouched.
   A coroutine rather than the sync method 17 wrote, because the
   in-flight predicate is exact only between ticks; T085's `Server.
   replace` is a coroutine anyway (its plan, step 8, gains an `await`).

   **`await Engine.unregister(name) -> list[int]`**: `KeyError` if not
   registered. Under `quiescent()`, in this order: `pools.unbind(name)`
   (no claim after this point can select the workflow — 04 §Dispatch
   order filters by the pool's bound names); `task_ids =
   scheduler.attempts_of(name)` (closed set: unbound and between
   ticks); `scheduler.cancel_attempts(task_ids)`; `del self.graphs[name]`.
   Then, outside the block, `await scheduler.wait_for(task_ids)` and
   return `task_ids`. The graph is dropped *after* the cancellations are
   issued, synchronously with them, so an attempt still inside
   `_load_run` is cancelled at that await and never reaches
   `_load_graph`; one before its first line never runs. What each
   cancellation does is the façade's and the lease service's own
   cancellation path — subprocess terminated then killed under
   `KILL_AFTER`, transcript flushed, stats entry `status=failed
   reason=shutdown` (`acp.py:740`), `released()` re-raising with no
   status (`services.py:744`), the runner's `finally` returning the
   slot and unregistering the context. **Nothing writes a task status**
   and the run row is not touched (D52, D221). The pool stays.
   `stop()` is unchanged.

   `register` is unchanged. Its "registering the same graph twice"
   refusal stays: `replace` is the verb for a swap.

### Recovery (`athanore/engine/recovery.py`)

8. **`recover(engine, workflows: Sequence[str] | None = None) -> list[int]`**.
   `None` is today's every registered workflow. A given list is checked
   against `engine.graphs` first — `KeyError` naming the unregistered
   names — because resetting the rows of a workflow nobody has bound is
   the defect the module docstring already describes (ready rows no
   pool can claim). Then, under `engine.scheduler.quiescent()`: `held`
   = the union of `engine.scheduler.attempts_of(w)` for the names, and
   one transaction `reset_for_recovery(names, exclude=held)` + the
   same `engine.recovered {task_ids}` event, emitted only when
   something was reset. `RecoverableEngine` gains `scheduler:
   Scheduler` (import the class; `scheduler` does not import
   `recovery`, so there is no cycle). At boot `held` is empty and the
   lock is free, so `start()`'s call behaves byte-for-byte as today.

   Why `exclude` exists although 22 §Add step 3 says nothing of the
   name is in flight at an `add`: a run whose task was `ready` when
   the workflow was removed sits claimable the moment `register` binds
   the name again, and T085's `add` runs `register` before `recover`
   (22 §Add's order). A tick in that gap claims the row, and a reset
   that did not exclude it would put two attempts on one task. The
   quiescent block makes `held` exact; `exclude` makes it matter.

### Runner and ops — unchanged, asserted

9. `runner._load_graph` reads `engine.graphs` by name at claim
   (`runner.py:275`) and the attempt keeps that object — `_record_
   success` routes on it — so **an attempt in flight finishes on the
   graph it started with, routing included**, and the *next* task
   dispatches on whatever `engine.graphs` holds then. `_load_node`
   raises `GraphError` for a node the graph lacks and `_record_failure`
   dead-letters it (D42). `ops._graph` reads `engine.graphs` at each
   call. Add the assertions (tests below); change no code in either
   module.

### Documents

10. **04 §Pools**: after the four MVP rules, one paragraph: a binding
    can be dropped (`unbind`) or moved (`rebind`) by a live
    registration; a move is refused while any attempt of the workflow
    is in flight — its leases belong to the pool they were claimed on,
    and re-binding under them would charge one pool's work to another's
    capacity (22 §Pools); a live registration names a pool that exists,
    never creates one.
11. **04 §Recovery on startup**: a new `### Live registration`
    subsection after the numbered list: the same reset runs for one
    name when it is added to a running server (`recover(engine,
    [name])`), between ticks, skipping rows an attempt of this process
    holds; `replace` swaps the graph and the next claim dispatches on
    it while attempts in flight finish on the one they started with;
    `unregister` unbinds the name, cancels its attempts exactly as
    §Shutdown step 3 does, writes no status (step 4), drops the graph
    and keeps the pool. One sentence pointing at 22 §Effects for the
    server's sequence around these.
12. **22 §Testing, *Engine* bullet**: `failed/unregistered` →
    `failed/shutdown`. §Remove step 1 and D221 are explicit that the
    stats entry is the façade's ordinary cancellation entry and the
    event says why; the bullet contradicts its own section.
13. **15-decisions**: rows D229 onward, one each, for the choices
    marked here — `attempts_of` sourced from the scheduler via
    `ClaimedTask.workflow` (not the live registry); `quiescent()` as
    the one between-ticks primitive and `unregister` unbinding first;
    `Engine.replace` a coroutine; `recover(engine, [name])` refusing
    unregistered names and excluding held rows; `replace(pool=)` reads
    a name and never creates or resizes; `KeyError` for lookups,
    `ValueError` for the in-flight refusal.
14. **17 § `### T083`**: the `**Status.** Done.` line, in the same commit.

## What this task is not

- No `Server` change, no `workflow.*` event, no `load_target`, no route,
  no CLI (T085, T086). `Server.register` still refuses a duplicate and
  still works only the way it does today.
- No plugin host change; a replaced graph's plugin spec is T084's and
  the server's to sequence.
- No new stats reason: the cancelled attempt records `reason=shutdown`
  as the façade does for any `CancelledError`; the *why* is T085's
  `workflow.unregistered`.
- No change to boot-time recovery semantics: `start()` calls
  `recover(self)` exactly as before.
- `LiveContext` is **not** changed. The brief proposed giving it a
  `workflow` so `attempts_of` could read the live registry; the
  registry cannot see an attempt between spawn and context binding, so
  the source is the scheduler and the protocol member would be dead.
- Snapshot untouched (`tests/snapshots/openapi.json`, `web/src/api/gen`).

## Files

`athanore/store/repos/tasks.py`, `athanore/engine/pools.py`,
`athanore/engine/scheduler.py`, `athanore/engine/__init__.py`,
`athanore/engine/recovery.py`; `tests/store/test_claim.py`,
`tests/store/test_tasks_repo.py`, `tests/engine/test_pools.py`,
`tests/engine/test_scheduler.py`, `tests/engine/test_replace.py` (new),
`tests/engine/test_unregister.py` (new), `tests/engine/test_recovery.py`,
`tests/engine/test_runner.py`, `tests/engine/test_ops_basic.py`;
`docs/v1/04-engine.md`, `docs/v1/22-live-registration.md`,
`docs/v1/15-decisions.md`, `docs/v1/17-serial-task-plan.md`.

## Tests

`tests/engine/`, on the `engines` / `start_engine` fixtures with plain
bodies unless a subprocess is the point; `tests/engine/test_shutdown.py`'s
`Sleeper` is the model for a body that parks until cancelled, and
`tests/agents/test_acp_outcomes.py`'s `Spy` + `scenario(sleep_s=30)`
is the model for an agent mid-turn (the fake sleeps before it touches
MCP, so no served API is needed).

- `test_pools.py`: `unbind` drops the binding, keeps the pool,
  `workflows_of` follows, `for_workflow` raises after; `rebind` moves
  and `workflows_of` of both pools follows; same-pool `rebind` is a
  no-op; both raise `KeyError` for an unbound name and `rebind` for an
  unknown pool.
- `test_scheduler.py` (on `Fleet`): `attempts_of` lists a running and
  a parked attempt of one workflow and not another's, and lists a
  re-dispatched id once; `wait_for` returns after the named attempts
  end and their slots are back, and skips ids nothing runs;
  `quiescent()` waits for a tick in progress (a body that blocks the
  claim's uow, or a `notify` raced against entry) and no claim happens
  inside the block though a ready row and a free slot exist.
- `test_replace.py` (new): two graphs under one name whose bodies leave
  distinguishable marks; start a run, let the first node claim, then
  `replace`; the attempt in flight finishes with the *old* body's mark
  and routes on the old graph; the next task runs the *new* body; a
  replacement lacking the next node dead-letters that task with
  `GraphError` in the failure entry; `replace` with a different pool
  raises `ValueError` while an attempt (running, and separately
  waiting on a `human_input`) is live and rebinds once it is done;
  the same pool with an attempt live is not refused; an unknown pool is
  `KeyError` and never creates one; an unregistered name is
  `KeyError`; a refusal leaves `graphs` and the binding as they were.
- `test_unregister.py` (new): with a `Spy` ACP body mid-turn,
  `unregister` returns the attempt's id, the child has a `returncode`,
  the transcript is flushed, a stats entry with `failed (shutdown)`
  exists, the task row is still `in_progress`, the run row is still
  `running`, `graphs` lacks the name, `workflows_of(pool)` lacks it,
  the pool is still registered with its slot back, `scheduler.in_flight`
  and `engine.live` no longer carry the id; a `waiting` attempt (a
  `human_input` body, via the `requests_service` fixture) is cancelled
  too and its row stays `waiting`; a ready task of the workflow is
  never claimed afterwards (notify, tick, assert still `ready`) while a
  sibling workflow on the same pool keeps running; an attempt spawned
  by the claim that raced the call is cancelled with the rest (submit
  under a body that holds the first slot, unregister as the second is
  claimed, assert two ids and no `attempt raised past the runner` in
  `caplog`); `unregister` on an unknown name is `KeyError`;
  `unregister` on a never-started engine drops the name and returns
  `[]`; `stop()` afterwards is quiet (no `engine.stopping`).
- `test_recovery.py`: after an `unregister`, `register` the name again
  and `recover(engine, [name])` resets exactly that workflow's rows,
  emits `engine.recovered` with their ids, and leaves another
  workflow's `in_progress` row (held by a live attempt) alone;
  `recover(engine, [name])` with nothing to reset emits nothing; a row
  of `name` held by a live attempt of this engine is excluded while a
  forced-`in_progress` row of the same name is reset; an unregistered
  name is `KeyError` and nothing is written.
- `test_runner.py` / `test_ops_basic.py`: one assertion each that the
  graph is read from `engine.graphs` at claim / at `submit` (swap the
  dict entry between two calls and observe which body / which start
  node is used).

## Verification

```sh
./scripts/test.sh -k "claim or tasks_repo or pools or scheduler or replace or unregister or recovery or runner or ops_basic"
./scripts/test.sh
git diff --exit-code tests/snapshots web/src/api/gen
```

## Done

- `Engine.replace`, `Engine.unregister`, `Engine.attempts_of`,
  `PoolRegistry.unbind`/`rebind`, `Scheduler.attempts_of`/`wait_for`/
  `quiescent`, `recover(engine, workflows)` exist with the semantics
  above; runner and ops untouched and asserted; 04 folded, 22's bullet
  corrected, decisions logged, T083 marked done; gate green; snapshot
  unchanged.

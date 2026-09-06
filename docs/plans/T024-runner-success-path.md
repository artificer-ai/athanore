# T024 — Runner: attempt lifecycle and the success path

**Task.** `docs/v1/17-serial-task-plan.md` § `### T024`.
**Specs.** `docs/v1/04-engine.md` §Attempt lifecycle, §Routing (including
the edge cases), §Output shape.

## What this task is

The thing that actually runs a node body: build the context, call the
function, interpret what comes back, write the outcome in one
transaction. The success path only.

## What this task is not

- **T024a** owns the `except` arm — failures, retries, timeouts,
  cancellation. Write the `try`/`finally`; leave the failure handling to
  it rather than half-implementing both.
- **T024b/T024c** own fan-out frames and joins. A list of transitions
  enqueues N tasks here; `branch` frames come later.
- **T025** owns the loop that calls this. Use the minimal engine stub the
  task describes (`store`, `settings`, `live`, `graphs`, `notify`); the
  real `Engine` is T027's.
- No agent code, no requests.

## Steps

1. `async def run_attempt(engine, claimed, lease)`: load the run and the
   node from the registered `Graph`; build `TaskContext` with
   `api_base = settings.public_url` and `token = claimed.token`;
   `live.register`; `bind_attempt` for logging; one uow emitting
   `task.started`, plus `run.started` when `claimed.run_started`.
2. Call the body: `edge_refs = [EdgeRef(e) for e in node.edges]`, and
   `kwargs = {node.payload_param: task.payload}` when the node has a
   payload slot. **A `None` payload is passed as `None`** — not omitted
   (04 §Routing edge cases). Wrap in
   `async with asyncio.timeout(node.timeout or None) as t:` and stash
   `ctx._timeout = t`, which is what T026 reschedules.
3. Success: `interpret(...)` then **one** uow —
   `finish(done, result=jsonable(value), terminal=not transitions)`;
   per transition `enqueue(...)` with `priority = explicit or
   -generation`, `explicit=bool(node.priority is not None)`, lineage
   `{"from": id, "reason": "transition"}`, `branch=task.branch`; emit
   `task.enqueued` per child and `task.done`.
4. If there are no transitions and `not has_pending(run)`:
   `set_status(run, completed, finished=now)` and `run.completed` with
   `output` per the shape rule (T015's `terminal_tasks`).
5. `finally`, on **every** path: `services.stream.close()`,
   `lease.release()`, `live.unregister`, `scheduler.notify()`.

## Careful

The uow must not span the body call. `AGENTS.md`: a UnitOfWork never
spans an await on a node body, an agent, or a request wait. Open one
before, one after; never one around.

## Verification

`tests/engine/test_runner.py`, against the stub engine:

- a plain return with one edge auto-transitions and carries the payload;
- a bare ref, a called ref, and a list of two refs each enqueue the
  expected rows;
- a terminal return completes the run and stores `output`;
- `current_task()` works inside the body and raises after;
- the context is unregistered in `finally` **even when the body raises**
  — the one failure-shaped test that belongs to this task.

## Done

- Tests pass; pyright strict clean on `athanore/engine`.
- `**Status.** Done.` on `### T024`, in the same commit.

## Files

```
athanore/engine/runner.py
tests/engine/test_runner.py
docs/v1/17-serial-task-plan.md
```

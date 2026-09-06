# 04 — Engine: graph, scheduling, execution

The engine is `athanore.graph` (pure) plus `athanore.engine` (asyncio,
store, events). It does not know agents exist; a node body is an opaque
coroutine. Everything the MVP's `graph.py`, `scheduler.py`, `pools.py`,
`runtime.py` and the operator handlers in `server.py` do lives here.

## Graph DSL

```python
from athanore import Workflow

wf = Workflow("feature_build")

@wf.node(start=True)
async def prompt(product): ...

@wf.node(retries=1, timeout=600)
async def review(engineering, qa): ...

@wf.node(priority=0)                     # explicit: jumps the queue
async def hotfix(git): ...

@wf.node()
async def architecture(engineering, *, deliverable): ...   # payload slot

@wf.node(join=True)
async def release(git, *, results): ...                    # fan-in (§Fan-in)
```

### Signature parsing (unchanged semantics)

- Positional-or-keyword and positional-only parameters are edges.
- If the signature has a `/`, the first parameter after it is the payload.
  Otherwise the first keyword-only parameter (after `*`) is the payload.
- `*args` / `**kwargs` are rejected.
- The edge refs injected are `EdgeRef` descriptors; `ref(payload)` returns
  a `Transition(target, payload)` — serializable, no callables.

### Node options (metadata seam)

| Option | Default | Meaning |
|---|---|---|
| `start` | False | Exactly one node per workflow |
| `priority` | None | Explicit dispatch priority; smaller first; beats all generation-based tasks in the run |
| `retries` | server `max_retries` | Attempts before dead-letter, per node |
| `timeout` | None | Wall-clock cap on one attempt of the body; raises `asyncio.TimeoutError` inside the body → normal failure path |
| `join` | False | The node closes a fan-out: it dispatches once, after every branch has transitioned into it, with the branch values in its payload slot (§Fan-in). Requires a payload slot |
| `label`, `description` | fn name / docstring | For the UI graph |

`pool=` on a node is a documented later seam, not built.

### Finalization

`wf.finalize()` runs once at registration (idempotent) and raises
`GraphError` on:

- zero or more than one start node;
- an edge naming a node that does not exist;
- duplicate node names;
- nodes unreachable from start;
- a workflow name that is not an identifier.

`server.register(wf, pool)` additionally rejects a workflow name that
collides with a CLI verb, a pool name, or an already registered workflow
(finalize cannot know those).

It computes `generation` by BFS from start (first reach for cycles) and
freezes the graph. The API exposes the finalized graph
(`GET /api/workflows`) including generations, so the SPA can lay out and
colour nodes without re-deriving anything.

## Routing interpretation

`engine.routing.interpret(node, value) -> list[Transition]`:

| Return value | Result |
|---|---|
| `Transition` | that transition |
| `EdgeRef` | `Transition(ref.name)` |
| non-empty list/tuple of refs/transitions | fan-out, one branch each |
| empty list/tuple (`[]`, `()`) | terminal whatever the node's edges, branch value `[]` (§Routing edge cases) |
| anything else, node has 0 edges | terminal (branch completes, `value` is the run output when last) |
| anything else, node has 1 edge | auto-transition carrying `value` as payload |
| anything else, node has ≥2 edges | `GraphError` (fails the attempt) |

A transition targeting an undeclared edge is a `GraphError`. Payloads are
coerced with `jsonable()` (pydantic models → dict, dataclasses → dict,
unknown → `str`).

A list is a fan-out only when *every* element is an `EdgeRef` or a
`Transition`. A list with anything else in it is a plain value like any
other, and takes the "anything else" rows: one edge carries it as the
payload, two or more are a `GraphError`.

### Routing edge cases

| Case | Behaviour |
|---|---|
| `return []` / `return ()` | Terminal for this branch, exactly like a plain value from a node with no edges; the branch value is `[]`. This holds whatever the node's edge count: an empty fan-out is not an error and is not the single edge's payload either, because a stage may legitimately decide there is nothing to split |
| `return [ref]` (one element) | A fan-out of one: identical to `return ref` except for the `task.enqueued` event, which is the same either way. No special case in code |
| Payload `None` arriving at a node with a payload slot | The slot is bound to `None`; bodies wanting a default write `*, payload=None`. The engine never omits a declared parameter |
| Payload given to a node with no payload slot | Dropped silently and recorded on the task row (`payload` column) so the timeline shows what was passed. Loop-backs rely on this (`return engineering` after `engineering(deliverable)` earlier) |
| Plain value from a node with one edge, value is itself a `Transition` to another node | The `Transition` wins (first row of the table); a body cannot "carry" a transition as a payload. Wrap it in a dict if that is really wanted |
| Terminal value under fan-out | Deterministic by shape, never by timing: if the run finishes with exactly one terminal task (linear, or a fan-out closed by a join), `run.output` is that task's value; if several branches terminate independently, `run.output` is the **list** of their values in branch order (frame indexes, outermost first). Every terminal task keeps its value in `tasks.result` with `terminal=true`, and `RunDetail.outputs` lists them with their branch keys (08). The recommended shape for a fan-out is to close it with a join so the output is one value |
| Non-JSON-able value | `jsonable()` falls back to `str()`; the engine logs at WARNING once per node when that fallback is hit, because it usually means a forgotten `output_model` |

### Failure classes (rule 3, refined)

Rule 3 says the exception is the failure policy; v1 lets the exception
*type* pick between the two policies the engine has:

| Raised | Policy |
|---|---|
| `GraphError` (routing to an undeclared edge, ambiguous plain return) | dead-letter immediately: it is a code defect, retrying reproduces it |
| `athanore.NonRetryable` (or a subclass) | dead-letter immediately: the body has decided a retry is pointless (a refused agent, a hard validation failure) |
| anything else, incl. `asyncio.TimeoutError` from `timeout` | retry up to `retries`, then dead-letter |

The MVP retried `GraphError` up to `max_retries`; that burned inference
on a typo. No new rule: still "raise to fail", the type is metadata.

### Timeouts (which clock, which error)

Three timeouts exist and they nest:

| Clock | Set by | Fires as | Policy |
|---|---|---|---|
| Node `timeout` | `@wf.node(timeout=…)` | `asyncio.TimeoutError` raised inside the body at the await it is parked on | Retryable (row 3 above). Paused while the task is `waiting` (§Waiting) |
| Agent `timeout` | `ACPAgent(timeout=…)`, default `settings.agent_timeout` (3 h) | The façade kills the subprocess, records stats with `status=failed reason=timeout`, raises `AgentError` | Retryable; a body that knows a retry is pointless converts it: `except AgentError as e: raise NonRetryable(e)` |
| `permission_timeout` / `human_input(timeout=)` | per agent class / per call | Engine-authored answer (agent) or `TimeoutError` in the body (node) | Neither fails the attempt by itself (05, 06) |

The agent timeout counts wall-clock time including operator waits on
permissions and elicitations (the agent process is alive); the node
timeout excludes `human_input` waits. A node timeout shorter than the
agent timeout it wraps is legal and simply wins. `AgentResult.status ==
"failed"` (refusal, cancel, truncation) is **returned, not raised**: the
body decides, and the default body pattern is `if not r.ok: raise
NonRetryable(r.error)` because those outcomes rarely improve on retry.

## Fan-in (join nodes)

Rule 2 lets a node fan out; without a counterpart no node can run *after
all branches*. v1 adds one: a node declared `join=True` collects a
fan-out. It is metadata on the node seam plus one engine mechanism,
branch frames; the three rules are unchanged.

```python
@wf.node()
async def product(architecture):
    spec = (await ProductManagerAgent().run()).output
    return [architecture(d) for d in spec.deliverables]     # fan-out: N branches

@wf.node()
async def qa(gate, *, deliverable): ...                     # each branch, on its own

@wf.node()
async def gate(release, engineering):
    ok = await run_tests()
    return release({"deliverable": ..., "ok": ok}) if ok else engineering

@wf.node(join=True)
async def release(*, results):                              # runs once, after every branch
    for r in results:                                       # r: {"index", "key", "value", "from_task"}
        ...
    return {"released": [r["value"] for r in results]}
```

### Branch frames

Every task carries `branch`: a stack of frames, outermost first. A
fan-out of N transitions from task T pushes
`{fanout: T, index: i, count: N, key: jsonable(payload_i)}` onto each
child's stack; single transitions, retries, reruns, and moves copy the
parent's stack unchanged. `key` is the payload the fan-out gave that
branch (the deliverable), which is the branch's identity (D4). Frames
nest: a branch that fans out again pushes a second frame.

### Arrival and dispatch

When a task transitions into a join node the engine does **not** enqueue a
task. In the same transaction that marks the source task `done`:

1. Pop the top frame. No frame → `GraphError` (routing into a join
   without a fan-out is a code defect).
2. Insert a `JoinArrival(run, join_node, fanout_task, index, key, value=
   transition payload, from_task)`; `(run, join_node, fanout_task, index)`
   is unique. Emit `join.arrived {join, fanout_task, index, count, arrived}`.
3. If `arrived == count`: enqueue one task at the join node with
   `payload = [ {index, key, value, from_task} … ]` ordered by `index`,
   `branch = frames[:-1]` (back at the fan-out's level, so nested joins
   compose), lineage `{from: fanout_task, reason: "join", arrivals: [task
   ids]}`, priority from the node as usual. Emit `task.enqueued
   reason=join`.

The join's payload slot therefore receives a list of dicts in fan-out
order, not arrival order. A join node MUST declare a payload slot;
`finalize()` rejects one that does not.

### Failure and operator semantics

- A branch that dead-letters never arrives; the run is `failed` by the
  dead-letter as usual — by the *first* one, if several branches
  dead-letter, since a failed run is re-opened only by retry, rerun or
  move (D103). Retrying or rerunning that branch later makes it
  arrive, the join fires, and the run re-opens to `running`: fan-in
  composes with the existing re-open semantics without new states.
- A run with no ready/in-progress/waiting tasks and a join with partial
  arrivals is a deadlock, not a completion: the runner marks it `failed`
  with error `join_incomplete: <join> has k of n arrivals` (03 invariant
  4). This also catches a fan-out where some branches terminate instead
  of joining, which is a routing mistake the operator sees immediately.
- A second arrival for an index (a branch retried after it arrived):
  before the join fired it replaces the stored value; after, it is
  recorded with `late: true`, does not re-fire the join, and the operator
  can `rerun` the join node (its payload is stored, so rerun replays the
  arrivals). Nothing is silently dropped.
- `move(task, join_node)` is rejected (409): moving bypasses arrival
  accounting. `set_status(join_task, ready)` and `rerun(run, join)` work
  as for any node.
- Recovery needs nothing new: arrivals are rows; the join task, once
  enqueued, is a task like any other.
- Fan-out to a join with `count == 1` fires on the first arrival, so a
  stage that "usually" splits still works when it produces one branch.

### What this does not do

There is no timeout on a join and no "first N of M" mode; a join waits for
every branch, and the operator's tools for a stuck branch are the ones
that already exist (retry, move, cancel). Partial joins are a later seam
on the same metadata (`join="any"`), not built.

## Scheduling

### Pools

A `Pool(name, capacity)` is a named concurrency cap. The default pool is
sized by `workers`. A workflow is registered on exactly one pool
(`server.register(wf, pool=…)`). Rules carried from the MVP:

- strict reservation — no lending between pools;
- `capacity=0` parks a workflow (queue only);
- names are unique and cannot collide with workflow names;
- a task's pool is derived from `run.workflow` and never changes.

New in v1: **slot leases**. The runner holds a `Lease` for the duration of
an attempt. `human_input` releases the lease while waiting and re-acquires
it before returning into the body (below). Leases are in-memory; a crash
frees them by definition.

### Dispatch order (per pool)

```sql
SELECT t.id FROM tasks t JOIN runs r ON r.id = t.run_id
WHERE t.status = 'ready' AND r.status IN ('queued', 'running')
  AND r.workflow IN (:pool_workflows)
ORDER BY r.position ASC,
         t.explicit DESC,
         CASE WHEN t.explicit THEN t.priority END ASC,
         CASE WHEN NOT t.explicit THEN t.priority END ASC,
         t.created DESC, t.id DESC
LIMIT :free
```

Semantics (identical to the MVP): run list position dominates; inside a
run explicit priorities first, then downstream-first (`-generation`), then
newest-first; retries keep their `created` so a flapping node cannot keep
jumping. The run's position is read through the join (the MVP's
`run_priority` snapshot on tasks, and the reorder code that kept it in
sync, are gone).

Claiming, in the same transaction: flip `ready → in_progress` with
`started=now`; **generate the task token** (`secrets.token_urlsafe`),
store its SHA-256 in `token_hash`, and return the clear text with the
claimed row (it lives only in the runner's memory from here); flip the
run `queued → running` (`run.started`) if this is its first claim. Tokens
are per attempt, so a recovered or retried task never reuses one.

### The loop

```
loop:
  reap finished attempts, release leases
  for pool in pools:
     free = capacity - leased
     while free > 0 and pool.readmit_queue: hand a lease to the oldest waiter; free -= 1
     if free > 0: claim(free) → spawn runner per task with a lease
  await wake (notify() or 1 s tick)
```

The re-admit queue is an in-memory FIFO per pool of tasks whose
`human_input` has been answered and are waiting to get their slot back
(§Waiting). It is drained before the store is asked for new work.

`notify()` is called after every operation that can make a task ready
(submit, answer, retry, rerun, move, resume, attempt finished).

## Running an attempt

`engine.runner.run_attempt(task)`:

1. Load run + node; bind `TaskContext`; publish `task.started`.
2. Call the body with edge refs (+ payload) under the node `timeout`.
3. Interpret the return value; in one transaction: mark task done with
   `result`, enqueue each transition (`task.enqueued` with
   `reason=transition`, `lineage.from=this task`; a fan-out pushes branch
   frames; a transition into a join node records an arrival and enqueues
   the join only when complete, §Fan-in), and if the run is **still
   `running`** and is left with no pending task: with a partial join,
   mark it `failed` (`join_incomplete`) whether or not this task
   transitioned — the branch that leaves a join short is one that *did*,
   into a join that could not fire; otherwise, if there were no
   transitions (`terminal=true`), mark the run `completed` with `output`
   (§Routing edge cases). The status is read in this same transaction:
   a run another branch has already `failed` by dead-lettering is left
   failed, because 03's run state machine re-opens a terminal run only
   by retry/rerun/move — settling it again would overwrite that verdict
   with `completed`, or emit a second `run.failed` for the stall the
   dead-letter caused (D103).
4. On exception: mark the task `failed` with `error`; append an engine log
   entry `attempt N failed: …`; if the exception is retryable (§Failure
   classes) and `attempt < retries` enqueue a retry (same payload, same
   `created`, `attempt+1`, `task.failed will_retry=true`); else mark
   `dead_letter`, and — if the run is **still `running`**, read in that
   same transaction — set run `failed` and publish `run.failed`. Two
   branches of one fan-out can dead-letter together; the first verdict
   is the run's, and the second records itself with `task.failed` and
   `task.dead_lettered` rather than emitting a second `run.failed` and
   re-stamping `finished` on a run nothing has re-opened (D103).
5. `finally`: release the lease, unbind the context, `notify()`.

`asyncio.CancelledError` is not a failure: an attempt cancelled by an
operator operation (cancel, move, delete, `set_status`) is recorded as
`cancelled` by that operation, not retried. On shutdown the attempt is
also cancelled but **its row is left untouched** (§Shutdown). Agent
subprocesses are killed by the façade's own `finally` (05) in both cases.

### TaskContext

Bound in a `ContextVar`; `current_task()` raises outside a body.

```python
@dataclass
class TaskContext:
    run_id: str; task_id: int; workflow: str; node: str; attempt: int
    token: str            # the task token (clear text only lives here and in the agent prompt)
    api_base: str         # settings.public_url
    services: TaskServices
    # declared by an agent façade for the duration of run():
    output_model: type[BaseModel] | None
    ask_policy: Literal["off", "http"]
    last_rejection: dict | None
    # engine-owned counters:
    request_ordinal: int  # nth human_input() call in this attempt (06 §Restart durability)
```

The runner registers every bound context in `engine.live` for the life
of the attempt. That registry is how the API validates a submission
against the declared `output_model` and checks `ask_policy` for `/ask`
(the MVP's `scheduler.context_for`).

`TaskServices` is the narrow surface bodies and façades use instead of the
raw store: `log.append(text, author=…)`, `stream.append(kind, text)`,
`submissions.latest()`, `requests.*` (06), `run.get()`. This is what lets
`agents` avoid importing `store`.

`last_rejection` is `{errors, schema, payload}`: what
`submissions.reject()` returned, plus the payload it was about. The 422
body is the `{errors, schema}` half; the payload is there because 19's
repair turn quotes it back to the agent and no event carries it (D120).

## Waiting on a human (new)

The MVP parked the body while still holding its worker slot; under
`workers=1` one playtest question stalled the whole server. v1:

```python
async def human_input(prompt, *, options=None, output_model=None, timeout=None):
    ctx = current_task()
    req = await ctx.services.requests.reopen_or_create(...)
    async with ctx.services.lease.released(req.id):  # task → waiting, slot freed
        answer = await ctx.services.requests.wait(req.id, timeout)
    # lease re-acquired here (may queue behind other ready tasks) → task in_progress
    return decode(answer)
```

- `released(request_id)` sets the task `waiting`, publishes
  `task.waiting`, and returns the lease to the pool — in that order, so
  the slot is never free while the store still says the task is running.
  The request id is the argument because both events carry it (18).
- Re-acquisition: when the answer arrives the task joins its pool's
  **re-admit queue**; the scheduler loop hands leases to that queue
  (FIFO by answer time) before it claims anything from the store. A
  resumed body therefore goes ahead of every `ready` task in the pool,
  including tasks of runs positioned above it: the body is mid-execution
  and holding state, and it already queued once. While queued the task
  stays `waiting`; it flips to `in_progress` (`task.resumed`) when the
  lease is handed over. The queue is in memory; a crash empties it and
  recovery handles the tasks. Cancellation — an operator op, a shutdown —
  is the one exit that re-acquires nothing: there is no outcome to record
  (§Shutdown) and the `waiting` row is recovery's. Every other exit,
  including a wait that timed out, takes a slot back before the runner
  records what the attempt did.
- The node `timeout` clock is **paused** while the task is `waiting`:
  the scope is disarmed on the way in (`reschedule(None)`) and re-armed
  on resume at `now + (deadline - released_at)`, what was left of the
  budget when the body parked (D108). A human taking a day must not fail
  an attempt capped at ten minutes of agent time — and an armed scope
  would not wait for the resume to say so, it would cancel the body
  inside the wait; bound the wait itself with `human_input(timeout=…)`.
- `pause` does not affect a waiting task; answering while paused resumes
  the body, and its successors wait for `resume` as before.
- Recovery: `waiting` → `ready`; the re-executed body finds its request
  by ordinal via `reopen` (06) and either takes the stored answer or
  re-parks, without asking twice.

Agent-side waits (permission, elicitation, HTTP ask) do **not** release
the slot: the agent process is alive and holding inference-adjacent
resources. Documented; the MVP behaved the same.

## Operator operations (`engine.ops`)

All operations are transactional, emit events, and `notify()` when they
may make work dispatchable.

| Op | Precondition | Effect |
|---|---|---|
| `submit(wf, title, description)` | wf registered | run `queued`, start task ready with `{title, description}` |
| `edit(run, title?, description?)` | title non-empty | `run.updated` |
| `reorder(run, direction \| index)` | | swap positions (`run.reordered`); dispatch reads `runs.position` directly, nothing to sync |
| `pause(run)` | `running` or `queued` | `paused`; in-flight tasks finish |
| `resume(run)` | `paused` | `running` |
| `cancel(run)` | not terminal | cancel ready/in-progress/waiting tasks (asyncio cancel + subprocess kill), run `cancelled` |
| `delete(run)` | any | cancel, then delete run and **all** child rows (tasks, log, events, submissions, stream, requests, answers) |
| `rerun(run, node)` | node exists | new task at node with the node's last payload and branch stack, attempt continues, run → `running` if terminal; for a join node the stored arrivals list is the payload |
| `retry(task)` | task not ready/in-progress/waiting | new task, same node/payload/priority, `attempt+1`, keeps `created`, run → `running` |
| `move(task, node)` | node exists, not a join node (409) | cancel the task (kill agent if in flight), new task at target with the same payload and branch stack |
| `set_status(task, ready\|cancelled\|dead_letter)` | | as named; `ready` re-dispatches, cancel kills agent |

Moving or retrying keeps the payload, which is the branch identity under
fan-out — carried from the MVP and still correct.

## Shutdown

`Server.stop()` (SIGINT, SIGTERM, `athanore serve` exiting, test teardown):

1. Stop claiming: the scheduler loop exits; the re-admit queue is dropped.
2. Emit `engine.stopping {task_ids}` for every in-flight attempt, in one
   transaction, so the audit trail shows the interruption.
3. Cancel every attempt's asyncio task. The façade's `finally` terminates
   the agent subprocess and, after a 5 s grace, kills it; the transcript
   flusher writes what it has; the stats entry is recorded with
   `status=failed reason=shutdown`.
4. **Do not write a task status.** Interrupted rows stay `in_progress` or
   `waiting`, which is exactly what §Recovery on startup resets to
   `ready`. A graceful stop and a crash therefore leave the store in the
   same state, and the re-execute-and-reattach posture (§Durability)
   applies to both. `cancelled` is reserved for operator intent.
5. Close SSE streams, flush the store, exit. Total budget 10 s; past it
   the process exits anyway (uvicorn's `timeout_graceful_shutdown`).

There is no "drain" mode in v1: agent attempts run for hours, so waiting
for them is not a shutdown. `athanore pause` on every run followed by
waiting for `tasks_in_progress == 0` in `/api/health` is the operator's
drain, and the CLI documents that recipe.

## Recovery on startup

1. Every `in_progress` or `waiting` task → `ready` (`started=NULL`,
   `token_hash=NULL`; a fresh token is minted at the next claim),
   `engine.recovered` event listing them.
2. Runs whose workflow is not registered stay as they are and are flagged
   `unregistered` in the API; they never dispatch.
3. Requests opened by a now-dead agent session stay in history as stale.

## Durability posture (unchanged decision)

`await agent.run()` and `await human_input()` hold the attempt. If the
server dies, the attempt re-executes from scratch; agent work must be
idempotent-ish, and `human_input` re-attaches to its request. Two-phase
suspension is a later seam only if it hurts.

## Programmatic host

```python
from athanore import Server, Pool
server = Server(settings)                # or Server() → settings from env/toml
server.register(feature_build, Pool("local", 1))
server.register(gamedev, Pool("local", 1))
server.register(msgtest)
server.serve()                           # blocking; or `await server.start()` / `.stop()` in tests
```

`wf.run(**settings)` remains the one-workflow shorthand. `athanore serve`
(11) is the CLI wrapper that discovers workflows and reads pools from
`athanore.toml`.

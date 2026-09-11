# 03 — Domain model

## Entities

```
Workflow 1──* Node                         (code, registered at startup; not stored)
Workflow 1──* Run 1──* Task                (stored)
Run 1──* LogEntry                          (the work log)
Run 1──* Event                             (audit + realtime)
Task 1──* Submission                       (agent values)
Task 1──* StreamChunk                      (agent output transcript)
Run 1──* JoinArrival                       (branches that reached a join)
Task 1──* Request 1──0..1 Answer           (human in the loop)
Pool *──* Workflow                         (registration-time; not stored)
```

### Workflow (code)

`name` (unique per server; `[a-z][a-z0-9_]*`; must not collide with a
CLI verb or a pool name, checked at `server.register`), `nodes`, `start`,
plugin declarations (09), `pool` binding. Immutable after finalization.

### Node (code)

`name`, `fn`, `edges: [name]`, `payload_param`, `start`, `join`
(collects a fan-out; 04 §Fan-in), `priority` (explicit override),
`generation` (computed), `retries` (override), `timeout` (override),
`pool` (later seam).

### Run

| Field | Type | Notes |
|---|---|---|
| `id` | ULID string | Sortable; URL-safe |
| `workflow` | str | Must be registered to dispatch; a run of an unregistered workflow is shown but parked |
| `title`, `description` | str | Operator-editable |
| `status` | enum | see state machine |
| `position` | int | List order; smaller dispatches first. **Renamed from `priority`** to stop colliding with node priority |
| `output` | JSON | The terminal node's return value (last branch) |
| `created`, `updated`, `finished` | timestamps | |
| `pending_requests` | derived | count of open requests |
| `current_nodes` | derived | nodes with in-progress or waiting tasks (plural: fan-out) |

### Task (one attempt of one node in one run)

| Field | Type | Notes |
|---|---|---|
| `id` | int | Autoincrement |
| `run_id`, `node` | | |
| `attempt` | int | 1-based; retries increment; reruns continue the count |
| `status` | enum | see state machine |
| `payload` | JSON | Incoming payload |
| `result` | JSON | Return value (jsonable) |
| `error` | str | Last failure |
| `priority`, `explicit` | int, bool | Dispatch key inside the run; the run's `position` is read through the join, not snapshotted (the MVP's `run_priority` column and its reorder sync are dropped) |
| `token_hash` | str | SHA-256 of the task token, set at **claim** (04); the token itself is never stored. NULL while `ready` |
| `stats` | JSON | The agent stats entry for this attempt (05), so run totals are a `SUM`, not an event scan |
| `created`, `started`, `finished` | timestamps | Retries keep `created` |
| `lineage` | JSON | `{"from": task_id, "reason": "transition|retry|rerun|move|manual_retry"}` for the timeline view |
| `terminal` | bool | Set when the task finished `done` with no transitions; its `result` is a branch output (04 §Routing edge cases) |
| `branch` | JSON | The fan-out frame stack this task runs under: `[{fanout: task_id, index, count, key}]`, outermost first; `[]` at top level (04 §Fan-in) |

### LogEntry (work log)

`id`, `run_id`, `node`, `author` ∈ {`agent`, `engine`, `user`}, `text`,
`created`, optional `task_id`, optional `kind` (`deliverable`, `note`,
`stats`, `failure`). Append-only. The `[stats]` line keeps its text form
and additionally carries the structured dict in the `run_stats` event.

### Event

`id` (monotonic int; the SSE cursor), `run_id?`, `task_id?`, `name`,
`data` JSON, `created`. The vocabulary is fixed (below) and shared with
plugin `refresh_on` and the SPA cache invalidation. One event,
`task.stream`, is **ephemeral**: published on the bus and the SSE feed
but never written to the table (below).

### Submission

`id`, `task_id`, `payload` JSON, `created`. Only payloads that passed the
declared model are stored; the latest wins for the body.

### StreamChunk

`id`, `task_id`, `seq`, `kind` ∈ {`text`, `thought`, `tool_call`,
`tool_result`, `notice`}, `text`, `created`. The agent transcript,
persisted in batches and subject to retention (07). Replaces the MVP's
`agent_progress` events.

### Request / Answer

See 06. `Request`: `id`, `run_id`, `task_id`, `prompt`, `mode` ∈
{`options`, `form`, `text`}, `source` ∈ {`agent`, `node`}, `kind` ∈
{`permission`, `elicitation`, `question`}, `options?`, `schema?`,
`tool_call?`, `created`. `Answer`: `request_id` (unique), `author` ∈
{`user`, `engine`}, `option_id?`, `value?`, `consumed`, `created`.

### Pool

`name`, `capacity`. Registration-time objects; in-flight counts are live
state in the scheduler, exposed by the API.

## State machines

### Run

```
queued ──dispatch──▶ running ──last branch lands──▶ completed
   │                   │  ▲
   │                   │  └──── retry/rerun/move ◀── failed
   │               pause│resume
   │                   ▼
   │                paused
   └───────cancel──────┴──────────────▶ cancelled
```

- `queued`: created, nothing dispatched yet (new in v1; the MVP showed
  `running` immediately). Makes "waiting for a slot" visible. The first
  claim of one of its tasks flips it to `running` (`run.started`).
- `running`: at least one task ready/in-progress/waiting.
- `paused`: dispatch blocked; an in-progress task finishes normally.
- `completed`, `failed`, `cancelled`: terminal but re-openable by
  retry/rerun/move (→ `running`), exactly as in the MVP.

### Task

```
ready ──claim──▶ in_progress ──return──▶ done
                   │   ▲                  
                   │   └──answer──┐
                   ├──human_input──▶ waiting ──cancel──▶ cancelled
                   ├──raise──▶ failed ──(attempt < retries)──▶ new task(ready)
                   │                └──(exhausted)──▶ dead_letter
                   └──cancel/move──▶ cancelled
```

- `waiting` is new: the body is parked in `human_input` and holds no pool
  slot (04). Recovery treats it like `in_progress` (→ `ready`; the body
  re-executes and re-attaches to its open request).
- `failed` is the record of an attempt; the retry is a new row with the
  same `created`. `dead_letter` is the final failed attempt.

### Request

`open` → `answered` (answer exists) → `consumed` (the waiter took it). A
request whose task is no longer in-progress/waiting is `stale`: shown in
history, not in the inbox, not answerable (409).

## Identifiers and ordering

- Run ids are ULIDs. Task, log, event, request ids are integers. Public
  URLs use them verbatim.
- Run list order is `position ASC`. New runs append at the bottom
  (`max+1`). Reorder is a swap with a neighbour or an explicit move to an
  index; positions are compacted lazily.
- Dispatch order within a pool (04): `runs.position ASC` (joined), explicit
  priority first (smaller first), then node priority (`-generation`,
  smaller first), then `created DESC`, then `id DESC`. Tasks re-admitted
  after a human wait go before any claim (04 §Waiting).

## Event vocabulary

Dotted names, `subject.verb`. Every event carries `run_id` and, where
applicable, `task_id`.

| Event | Data | Emitted by |
|---|---|---|
| `run.created` | workflow, title | submit |
| `run.started` | first task | claim (`queued` → `running`) |
| `run.updated` | changed fields (incl. `status` when an op re-opens a terminal run) | edit, ops |
| `run.reordered` | position | reorder/swap |
| `run.paused` / `run.resumed` / `run.cancelled` / `run.deleted` | note | ops |
| `run.completed` / `run.failed` | node, error | runner |
| `task.enqueued` | node, attempt, reason, from_task | runner/ops |
| `join.arrived` | join, fanout_task, index, count, arrived, late | runner |
| `task.started` | node, attempt | runner |
| `task.done` | node | runner |
| `task.failed` | node, attempt, error, will_retry | runner |
| `task.dead_lettered` | node, error | runner |
| `task.waiting` / `task.resumed` | request_id | human_input |
| `task.cancelled` / `task.moved` / `task.status_set` | from, to | ops |
| `task.stream` | task_id, seq_from, seq_to | stream flusher. **Not persisted**: bus + SSE only, no `id:` line; content lives in `StreamChunk` and late joiners fetch `/stream?after=` |
| `submission.accepted` / `submission.rejected` | payload / errors | agent API |
| `submission.repair` | turn, reason | façade |
| `request.opened` / `request.answered` | request_id, mode, kind, author | requests |
| `log.appended` | log_id, author, node | log |
| `agent.stats` | stats dict | façade |
| `engine.recovered` | task ids | startup |
| `engine.stopping` | task ids | shutdown (04 §Shutdown) |
| `workflow.registered` | workflow, pool, target | live registration (22 §Events) |
| `workflow.replaced` | workflow, pool, target | live registration (22 §Events) |
| `workflow.unregistered` | workflow, task ids | live registration (22 §Events) |
| `plugin.<wf>.<name>` | free | plugin handlers (namespaced) |

Payload shapes per event are fixed in 18. Persisted events are the SSE feed (08). `task.stream` is the one
exception: at 2–3 flushes per second per streaming task it would be most
of the table, and it carries no state a late joiner cannot rebuild from
`StreamChunk`, so it is never stored. The MVP's `transition` event is
folded into `task.enqueued` (`reason=transition`, `from_task`).

## Invariants (enforced in code, tested)

1. A submission never creates a transition. Only a returning body does.
2. An answer is claimed by exactly one waiter, keyed by request id.
3. A task's pool is derived from its run's workflow and never changes.
4. A run is `completed` only when it has no ready/in-progress/waiting tasks,
   no join with partial arrivals, and the last finishing branch had no
   successors. No pending tasks with a partial join is `failed`
   (`join_incomplete`), never `completed`.
5. Task tokens are never returned by any operator endpoint and never
   stored in clear text.
6. Retries preserve `created`; reruns and moves get a fresh `created`.
7. Every state-changing operation emits at least one event in the same
   transaction (outbox), so the SSE feed never disagrees with the store.
   Appending stream chunks is not a state change (`task.stream` is
   ephemeral).
8. A routing error (`GraphError`) or a `NonRetryable` exception
   dead-letters the task on the first attempt; only other exceptions are
   retried (04).

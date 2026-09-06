# 18 — Event payloads (normative)

03 fixes the event *names*; this appendix fixes the *data* each one
carries. It is the contract the SPA invalidation table, plugin
`refresh_on` handlers, `athanore logs -f`, and the generated TypeScript
union depend on (D53).

## Envelope

Every event, stored or ephemeral, is:

```json
{"id": 4821, "run_id": "01J…", "task_id": 17, "name": "task.done",
 "data": {…}, "created": "2026-09-05T14:02:11.482Z"}
```

- `id` is the SSE cursor; absent on ephemeral events (`task.stream`).
- `run_id` is present on every event except `engine.*`.
- `task_id` is present on every `task.*`, `submission.*`, `request.*`,
  `agent.*` event and on `log.appended` when the entry has a task.
- `data` is one of the objects below. Fields marked `?` may be absent;
  nothing is ever `null`-filled to keep a shape (01 §Real data only).

## Typing

`athanore/events/payloads.py` declares one pydantic model per event
name (`RunCreated`, `TaskEnqueued`, …) and an `EventEnvelope`
discriminated on `name`: one envelope class per name (`RunCreatedEvent`,
…), each fixing the type of its `data`, so the union is tagged by a field
the payloads themselves do not carry. `athanore/api/schemas/events.py`
re-exports them rather than restating them (D81). `GET /api/runs/{id}/events` and
the SSE `data:` line serialise that envelope, so `openapi.json` carries a
`oneOf` per event and `@hey-api/openapi-ts` emits a discriminated union.
`plugin.*` events fall through to `PluginEvent` with `data: dict`. A test
asserts every `EventName` has a model and every emitted event validates
against it (13 §Contract tests).

## Payloads

### Runs

| Event | data |
|---|---|
| `run.created` | `{workflow: str, title: str, position: int}` |
| `run.started` | `{task_id: int, node: str}` — the first claim |
| `run.updated` | `{changed: {title?: str, description?: str, status?: RunStatus}}` — only the fields that changed |
| `run.reordered` | `{position: int, previous: int}` |
| `run.paused` | `{}` |
| `run.resumed` | `{}` |
| `run.cancelled` | `{cancelled_tasks: [int]}` |
| `run.deleted` | `{workflow: str, title: str}` — the last event of a run; it is deleted with the run, so SSE clients see it live only |
| `run.completed` | `{node: str, task_id: int, output: json, terminal_tasks: [int]}` — `output` follows the shape rule of 04 §Routing edge cases; `node`/`task_id` are the last landing task |
| `run.failed` | `{node: str, task_id: int, error: str, code?: "join_incomplete"}` — `code` is set when the run stalled on a partial join rather than a dead-letter |

### Tasks

| Event | data |
|---|---|
| `task.enqueued` | `{node: str, attempt: int, reason: "start" \| "transition" \| "retry" \| "rerun" \| "move" \| "manual_retry" \| "set_status" \| "join", from_task?: int, payload_present: bool, branch: [{fanout: int, index: int, count: int}]}` — `branch` omits `key` (it can be large); for `reason=join`, `from_task` is the fan-out task and `data.arrivals: [int]` lists the arriving tasks |
| `join.arrived` | `{join: str, fanout_task: int, index: int, count: int, arrived: int, late: bool}` — one per branch reaching a join; `arrived == count` means the join task was enqueued in the same transaction |
| `task.started` | `{node: str, attempt: int}` |
| `task.done` | `{node: str, attempt: int, transitions: [str], terminal: bool}` |
| `task.failed` | `{node: str, attempt: int, error: str, retryable: bool, will_retry: bool, retry_task_id?: int}` |
| `task.dead_lettered` | `{node: str, attempt: int, error: str}` |
| `task.waiting` | `{node: str, request_id: int}` |
| `task.resumed` | `{node: str, request_id: int, waited_s: float}` |
| `task.cancelled` | `{node: str, from: TaskStatus, reason: "cancel" \| "move" \| "delete" \| "set_status"}` |
| `task.moved` | `{node: str, to: str, new_task_id: int}` |
| `task.status_set` | `{node: str, from: TaskStatus, to: TaskStatus}` |
| `task.stream` | `{seq_from: int, seq_to: int}` — ephemeral; content via `GET /api/tasks/{id}/stream?after=` |

### Submissions and requests

| Event | data |
|---|---|
| `submission.accepted` | `{node: str, submission_id: int}` — the payload itself is not in the event; fetch the task |
| `submission.rejected` | `{node: str, errors: [{loc: [str \| int], msg: str, type: str}]}` |
| `submission.repair` | `{node: str, turn: int, reason: "nothing_submitted" \| "rejected"}` |
| `request.opened` | `{request_id: int, mode: RequestMode, kind: RequestKind, source: RequestSource, node: str, ordinal?: int}` |
| `request.answered` | `{request_id: int, author: "user" \| "engine", option_id?: str}` — `value` is not in the event (may be large or sensitive); fetch the request |

### Log and stats

| Event | data |
|---|---|
| `log.appended` | `{log_id: int, author: LogAuthor, node: str, kind?: LogKind, preview: str}` — `preview` is the first 200 characters |
| `agent.stats` | the stats entry of 05 §Stats entry verbatim: `{node, attempt, status, reason?, model?, input_tokens?, output_tokens?, total_tokens?, tool_calls?, cost?, duration_s, session_id?, repair_turns?, denied_permissions?}` |

### Engine

| Event | data |
|---|---|
| `engine.recovered` | `{task_ids: [int]}` — rows reset to `ready` at startup (no `run_id`) |
| `engine.stopping` | `{task_ids: [int]}` — attempts interrupted by a shutdown (04 §Shutdown; no `run_id`) |

### Plugins

`plugin.<workflow>.<name>` carries whatever the handler passed to
`ctx.services.events.publish(name, data)`; `data` MUST be a JSON object.
The registry rejects names with fewer than three segments or a workflow
segment that is not the publishing workflow.

## Rules

1. Adding a field is a minor change; removing or renaming one is a major
   change (08 §Versioning).
2. Payloads never carry tokens, full log text, full submission payloads,
   or answer values. Consumers fetch those by id.
3. Every event is emitted inside the transaction that made the change it
   describes (03 invariant 7), so a consumer that fetches on receipt sees
   the new state.

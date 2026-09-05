# 08 — HTTP API and event stream

FastAPI. One versioned surface under `/api/` (v1 is unversioned in the
path; a breaking change introduces `/api/v2/` — see §Versioning). The SPA
is served at `/`, plugin assets at `/plugins/{wf}/static/`, OpenAPI at
`/openapi.json`, `/docs`, `/redoc`.

## Conventions

- JSON in, JSON out. Bodies are pydantic models; validation errors are
  **422** with `{"error": "validation failed", "code": "validation",
  "errors": [{loc, msg, type}]}` (the MVP's 400-for-parity rule is
  dropped; v1 is a new contract).
- Every error: `{"error": "<human message>", "code": "<stable snake_case>",
  ...extras}`. Codes: `not_found`, `conflict`, `forbidden`,
  `unauthorized`, `validation`, `invalid_option`, `already_answered`,
  `stale_request`, `graph_error`, `unknown_workflow`, `unknown_node`,
  `payload_too_large` (413), `plugin_error` (a `PluginError` from a handler).
- Status codes: 200/201/204, 400 (malformed), 401 (missing/invalid
  operator token on a network bind), 403 (wrong task token, policy off),
  404, 409 (state conflict), 422 (validation), 413 (body too large).
- Timestamps are ISO-8601 UTC strings. Ids as in 03.
- Lists paginate with `?limit=&cursor=` where noted; run lists are small
  and return whole.
- Non-native values serialise via `default=str`.

## Authentication (12 has the model)

Athanore is a local tool. On the default loopback bind there is **no
operator authentication**: the SPA and the CLI call the API plainly. The
only credential that always exists is the per-task token, which lets an
agent act on exactly one task.

| Surface | Loopback (default) | Non-loopback bind |
|---|---|---|
| Operator endpoints, SSE, plugin routes/actions | none (unless `require_token`) | `Authorization: Bearer <operator token>` |
| Agent endpoints (`/api/agent/tasks/{id}/…`) | `X-Athanore-Token: <task token>` | same |
| Static SPA, `/api/health`, `/api/me`, `/openapi.json` | none | none |

"Loopback" is decided by the configured bind host (`is_loopback` or
`localhost`), never by the peer address of a request. A reverse proxy in
front of a loopback bind sets `require_token=true` (12).

When a token is required, SSE (which cannot set headers from a browser)
also accepts it as `?access_token=` on `GET /api/events` only; the server
does not log that query string.

## Endpoints

### Workflows

| Method | Path | Body → Response |
|---|---|---|
| GET | `/api/workflows` | `[{name, start, pool, capacity, in_flight, nodes: {name: {edges, generation, priority, retries, timeout, label, description}}, plugin: {panels, actions}}]` |
| GET | `/api/workflows/{name}` | one of the above (404) |
| GET | `/api/workflows/{name}/source` | `{file, source, nodes: {name: {line}}}` — the module source via `inspect`, for the workflow library overlay |
| POST | `/api/workflows/{name}/runs` | `{title, description?}` → 201 `{run_id}` |

### Runs

| Method | Path | Body → Response |
|---|---|---|
| GET | `/api/runs` | `?status=&workflow=` → `[RunSummary]` (id, workflow, title, status, position, current_nodes, pending_requests, created, updated, unregistered) |
| GET | `/api/runs/{id}` | `RunDetail` = summary + description, output, tasks `[TaskRow]` (no tokens), stats totals |
| PATCH | `/api/runs/{id}` | `{title?, description?}` → `RunDetail` |
| DELETE | `/api/runs/{id}` | 204 |
| POST | `/api/runs/{id}/pause` `/resume` `/cancel` | → `{ok, note?}`; 409 on wrong state |
| POST | `/api/runs/{id}/rerun` | `{node}` → `{task_id}` |
| POST | `/api/runs/{id}/position` | `{direction: -1\|1}` or `{index}` → `{position}` |
| POST | `/api/runs/{id}/log` | `{text}` → `{log_id}` (author `user`, node = current node or `user`) |
| GET | `/api/runs/{id}/log` | `[LogEntry]` |
| GET | `/api/runs/{id}/events` | `?after=&limit=` → `[Event]` |
| GET | `/api/runs/{id}/requests` | `[RequestView]` |
| GET | `/api/runs/{id}/graph` | the workflow graph with per-node state for this run (below): `{nodes: [{name, generation, join, state, live, attempts, last_task_id, branches: [{from_task, tasks: [int]}], arrivals?: {arrived, count}}], edges: [{from, to, kind: forward\|back\|join, traversed: n}]}` |

#### Graph semantics

- `state` is derived from the node's tasks in this run with this
  precedence, first match wins: `in_progress` → `waiting` → `ready` →
  `dead_letter` → `failed` (a failed attempt with a retry still pending
  reports `ready`, because the retry row exists) → `done` → `cancelled` →
  `idle` (no task ever). The SPA colours by `state` alone (10 §Status
  colours).
- `live` is `state ∈ {in_progress, waiting}` or the node has at least one
  `done` task. It is the liveness flag for `node`-slot plugin panels (09
  §Slots), computed here so the manifest can stay static.
- `attempts` counts every task row for the node; `last_task_id` is the
  highest id, the one the task drawer opens.
- `branches` groups the node's tasks by the fan-out that produced them:
  `from_task` is the `lineage.from` of the first task in the branch chain
  whose parent returned a list. Nodes reached by a single path have one
  branch with `from_task: null`. The SPA renders one indented sub-list per
  branch (10 §Graph pane).
- `edges` are the finalized graph's edges; `kind` is `back` when the target's
  generation is ≤ the source's (a loop-back, drawn as a rail), `join` when
  the target is a join node, else `forward`. `traversed` counts
  `task.enqueued reason=transition` events from a task of `from` to a
  task of `to`, plus `join.arrived` events for `join` edges.
- Join nodes carry `join: true` and, while a fan-out is open, `arrivals:
  {arrived, count}` for the innermost pending fan-out, so the SPA can show
  `2 of 3 arrived` (10 §Graph pane).
- `POST /api/runs/{id}/position`: `{direction: -1 | 1}` swaps with the
  neighbour above or below (no-op at the ends, still 200 with the current
  position); `{index: n}` moves to the **zero-based** list index, clamped to
  `[0, count-1]`. New Run's "top" is `{index: 0}`; "bottom" is the default
  (append), no call needed.
- `RunDetail.output` is one value when the run ended with a single
  terminal task and a list, in branch order, when several branches
  terminated independently (04 §Routing edge cases, D58). `RunDetail.
  outputs` is always a list: `[{task_id, node, branch: [{index, key}],
  value}]`, one entry per terminal task, so consumers that want the
  per-branch view never have to inspect the shape of `output`.
  `RunDetail.tasks[].terminal` and `tasks[].branch` are exposed too.

### Tasks (operator)

| Method | Path | Body → Response |
|---|---|---|
| GET | `/api/tasks/{id}` | `TaskRow` + `submissions` (operator view; no token in response) |
| GET | `/api/tasks/{id}/stream` | `?after=<seq>&limit=` → `{chunks: [{seq, kind, text, created}], last_seq, live}` |
| POST | `/api/tasks/{id}/retry` | → `{task_id}` |
| POST | `/api/tasks/{id}/move` | `{node}` → `{task_id}`; 409 `conflict` when `node` is a join node (04 §Fan-in) |
| POST | `/api/tasks/{id}/status` | `{status: ready\|cancelled\|dead_letter}` → `{ok}` |

### Agent-facing (task token; own prefix, tagged `agent` in OpenAPI)

Everything an agent may call lives under `/api/agent/`, on its own
router with the task-token dependency, the body limit, and its own
response models. The MVP overloaded `/api/tasks/{id}` and picked the
response shape by credential; that cannot be expressed in OpenAPI
without `oneOf` tricks and made the auth dependency decide two things.

| Method | Path | Body → Response |
|---|---|---|
| GET | `/api/agent/tasks/{id}` | `{task_id, run_id, workflow, node, attempt, title, description, input, output_schema?, log: [LogEntry]}` — `output_schema` is the declared `output_model`'s JSON schema when one is live (the `native` tier reads it, 05); `log` is the run's work log **excluding `kind=stats` lines**, oldest first, uncapped (below) |
| POST | `/api/agent/tasks/{id}/log` | `{text}` → `{log_id}` (author `agent`) |
| POST | `/api/agent/tasks/{id}/submit` | any JSON (≤ `body_limit`) → `{ok}`; 422 + `{errors, schema}` when an `output_model` is declared and the payload misfits; 409 if the task is not in progress |
| POST | `/api/agent/tasks/{id}/ask` | `{prompt, options?: [str\|{option_id,name,kind?}], schema?}` → `{request_id, mode}`; 403 unless `ask_policy=http` |
| GET | `/api/agent/tasks/{id}/requests/{rid}` | `?wait=<s≤120>` → `{answered: false}` \| `{answered: true, answer, answered_by}` |

What the agent reads: the work log is the inter-stage channel (D4), so
the agent gets every `agent` and `user` entry and the engine's `failure`
entries (a retried attempt should know why the last one failed), but not
the `[stats]` lines: token counts and costs are operator information and
only distract a model. Entries are complete (no truncation) and ordered
by id; the log is bounded by the number of stages, not by agent output,
so no cap is applied. `input` is the task payload as stored, `null` when
none.

The token is valid only for the attempt it was minted for (04 §Dispatch)
and only while that task is `in_progress` or `waiting`; 403 otherwise.
It is accepted in the `X-Athanore-Token` header only and never appears
in any operator response. The `output_model` used by `/submit` is read
from the live `TaskContext` (`engine.live.context_for`); a task with no
live context is by definition not in progress → 409.

### MCP (agent-facing, task token)

`POST /mcp/agent` is a Model Context Protocol server (streamable HTTP
transport, `mcp` Python SDK, mounted as a sub-application) authenticated
by the same `X-Athanore-Token` dependency as `/api/agent/`. It is the
`mcp` tooling tier of 05 and is a thin adapter over the same services
the REST routes call; nothing is reachable through it that is not
reachable through `/api/agent/`.

| Tool | Input | Result |
|---|---|---|
| `get_task` | `{}` | the `GET /api/agent/tasks/{id}` body |
| `append_log` | `{text: str}` | `{log_id}` |
| `submit_result` | the node's `output_model` JSON schema when declared, else any object | `{ok: true}`; on a misfit the tool returns `{ok: false, errors, schema}` with `isError` set, so the model retries in-turn |
| `ask_operator` | `{prompt, options?, schema?, wait?: int ≤ 120}` | `{request_id, mode, answered, answer?}`; 403 semantics as `/ask` (`ask_policy`) |
| `wait_answer` | `{request_id, wait?: int ≤ 120}` | `{answered: false}` \| `{answered: true, answer, answered_by}` |

The task id is the token's, never an argument: a token cannot name another
task. Tool descriptions carry the same wording as the 19 kickoff so the
model's instructions and its tools agree. The endpoint is listed in
OpenAPI under the `agent` tag as an opaque route (its schema is MCP's,
not REST) so the snapshot records its existence and auth scheme.

### Requests (operator)

| Method | Path | Body → Response |
|---|---|---|
| GET | `/api/requests` | `?pending=true&run=` → `[RequestView]` (the inbox) |
| GET | `/api/requests/{id}` | `RequestView` |
| POST | `/api/requests/{id}/answer` | `{option_id}` \| `{value}` → the updated `RequestView`; 400 `invalid_option`, 409 `already_answered` / `stale_request`, 422 validation |

`RequestView`: `{id, run_id, task_id, node, prompt, mode, source, kind,
options, schema, tool_call, pending, answer, answered_by, created, age}`.

### Plugins (09)

| Method | Path | Response |
|---|---|---|
| GET | `/api/plugins` | manifest |
| POST | `/api/plugins/{wf}/actions/{name}` | `{scope: {run_id?, task_id?, node?}, input}` → handler result (JSON) |
| * | `/api/plugins/{wf}/...` | plugin routes |
| GET | `/plugins/{wf}/static/...` | plugin assets |

### Events (SSE)

`GET /api/events?after=<event id>&run=<id>&names=run.*,task.*`

- `text/event-stream`; each message: `id: <event id>`, `event: <name>`,
  `data: <json Event>`. Ephemeral events (`task.stream`) are sent without
  an `id:` line, so a reconnecting client's `Last-Event-ID` always names
  a stored event.
- `after` (or the `Last-Event-ID` header on reconnect) replays from the
  store, then switches to live. Replay is capped at 5000 events; beyond
  that the client receives `event: resync` and refetches.
- Filters are server-side (`names` accepts globs); the SPA opens one
  stream per tab.
- Implemented with `sse-starlette` (`EventSourceResponse`): keep-alive
  ping, client-disconnect detection, and graceful shutdown come from the
  library; replay-then-live and `Last-Event-ID` handling are ours.
- Keep-alive comment every 15 s; the server closes idle streams on
  shutdown.
- `task.stream` events carry `{task_id, seq_from, seq_to}`; the client
  fetches chunks. This keeps the SSE feed small and lets late joiners
  catch up from the store.
- Every `data:` line is an `EventEnvelope` whose payload shape per event
  name is fixed in 18 and typed in OpenAPI as a discriminated union, so
  the generated client gives the SPA a typed `switch` on `name` (D53).

### System

| Method | Path | Response |
|---|---|---|
| GET | `/api/health` | `{ok, version, runs_running, tasks_in_progress, pools: {name: {capacity, in_flight}}}` — unauthenticated, no ids |
| GET | `/api/me` | `{auth: "off"\|"token", authenticated: bool, version, started_at, features}` — unauthenticated so the SPA can decide whether to show the token screen; `started_at` changes on restart, which is the SPA's cue to refetch the plugin manifest (09) |

## OpenAPI

- Every route has typed request/response models; tags: `workflows`,
  `runs`, `tasks`, `requests`, `agent`, `plugins`, `events`, `system`.
- Security schemes: `taskToken` (apiKey header) on agent routes and
  `operatorBearer` (http bearer) on operator routes, the latter enforced
  only on a network bind.
- `openapi.json` is snapshot-tested (13) and feeds `@hey-api/openapi-ts`
  for the SPA client (types, fetch client, TanStack Query options), so a
  contract change fails CI on both sides. The event-name and error-code
  enums are referenced from `Event.name` / `ApiError.code`, which is how
  the TypeScript unions in 13 are generated.

## Sizes

Body limit `body_limit` (1 MiB default) on every JSON endpoint; 413
beyond. Neither FastAPI nor Starlette ships this: it is a ~30-line ASGI
middleware that checks `Content-Length` and caps the receive stream.
Rate limiting is a later seam, not built.

## Versioning

The API is versioned by the package version. Additive changes (new
fields, new endpoints, new event names) are minor releases. Removing or
renaming is a major release and ships under `/api/v2/` with `/api/`
proxying for one minor cycle. The event vocabulary is part of the
contract.

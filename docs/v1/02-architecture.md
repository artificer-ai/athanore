# 02 — System architecture

## Processes

```
┌─────────────────────────────── athanore serve ───────────────────────────────┐
│                                                                              │
│  FastAPI app ──────────── Engine ──────────── Store (SQLAlchemy async)        │
│   ├ operator API          ├ scheduler          ├ SQLite (default, WAL)        │
│   ├ agent API (tokens)    ├ pools              └ Postgres (optional)          │
│   ├ SSE /api/events       ├ task runner                                       │
│   ├ plugin routes         └ recovery          EventBus (in-process pub/sub)   │
│   ├ static SPA + assets                        └ persists → events table      │
│   └ OpenAPI                                    └ fans out → SSE clients       │
│                                                                              │
│  Agent subprocesses (ACP over stdio): npx pi-acp | claude-agent-acp | docker  │
└──────────────────────────────────────────────────────────────────────────────┘
        ▲ HTTP+SSE                   ▲ HTTP (task token)           ▲ HTTP+SSE
   Browser SPA                    agents (curl)                  athanore CLI
   (loopback: no auth; network bind: bearer token)
```

One process, one store, one event bus. That is a deliberate v1 limit
(01 §Non-goals). Every boundary inside the process is an interface so a
later split (workers in another process, a shared broker) does not change
callers.

## Package layout

Monorepo with one Python distribution and one npm workspace.

```
athanore/                      Python package (distribution "athanore")
  __init__.py                  public API surface (see below)
  settings.py                  pydantic-settings: AthanoreSettings
  logging.py                   structlog config: configure_logging, bind_attempt,
                               get_logger; routes stdlib logging through structlog
  workflow.py                  Workflow: the user-facing object. Owns a graph
                               builder and the plugin declarations (09); the
                               only module that imports both.
  server.py                    Server: the composition root (04 §Programmatic host).
                               Above every tier; nothing in the package imports it.
  graph/                       signature parsing + validation. Pure; no I/O, no asyncio.
    builder.py                 GraphBuilder, node(), EdgeRef, Transition
    model.py                   Graph, Node (frozen dataclasses)
    validate.py                finalize(): errors listed in 04
    json.py                    jsonable(): what the engine may persist
  engine/                      execution. Depends on graph, store, events.
    scheduler.py               dispatch loop, pools, claiming, re-admit queue
    live.py                    registry of in-flight TaskContexts (context_for(task_id))
    runner.py                  runs one attempt: context, body, routing, outcome
    routing.py                 interpret(return value) → transitions
    pools.py                   Pool, capacity accounting, slot lease
    recovery.py                startup recovery
    context.py                 TaskContext, current_task()
    services.py                TaskServices: the narrow store surface a body gets
    errors.py                  NonRetryable, the failure classes, operation refusals (D42)
    ops.py                     operator operations (pause, cancel, rerun, move…)
  requests/                    human-in-the-loop channel (06)
    service.py                 create / answer / wait / reopen
    validators.py              pydantic + light JSON-schema validators
    human.py                   human_input()
    errors.py                  the five refusals of the channel
  agents/                      façade (05)
    base.py                    Agent, AgentResult, prompts, kickoff
    acp.py                     ACPAgent + ACPClient
    policies.py                permission / elicitation / ask policies
    submissions.py             declare/attach/repair
    stats.py                   stats entry building; SessionStatsProvider protocol
  events/
    bus.py                     EventBus: publish(Event) → persist + subscribers
    names.py                   the event vocabulary (StrEnum) and glob matching
    model.py                   Event: the envelope the bus publishes and the store keeps
    payloads.py                one typed payload model per event name (18)
  store/
    tables.py                  SQLAlchemy 2.0 Core metadata (Table objects, no ORM)
    rows.py                    domain enums + the read models the repositories return
    repos/                     one repository per aggregate (runs, tasks, log, …)
    uow.py                     Store, UnitOfWork (transaction + outbox), Reader
    engine.py                  the async engine factory (WAL, per-connection settings)
    clock.py                   now(): the store's one clock
    retention.py               the periodic prune (07 §Retention)
    migrate.py                 Alembic, driven programmatically
    migrations/                Alembic environment + versions
    legacy.py                  v0 athanore.db importer
  plugins/                     (09)
    decl.py                    Route, Action, Panel, Handler declarations
    registry.py                collect, validate, build manifest
    context.py                 PluginContext: what a handler is handed, and its scope
    mount.py                   mount routers, actions, assets
    discovery.py               entry-point discovery (09 §Discovery)
    builtin/                   the core-shipped panes (overview, log, agent, graph, requests)
  api/                         (08)
    app.py                     create_app(settings, engine, store, plugins)
    deps.py                    auth dependencies (operator bearer, task token)
    errors.py                  ErrorCode, ApiError → {"error", "code", ...}
    middleware.py              the request-body cap (08 §Sizes)
    openapi.py                 what the generated document says about itself
    schemas/                   pydantic response/request models
    routers/                   system, workflows, runs, tasks, requests, agent
    mcp.py                     /mcp/agent: the agent surface as MCP tools (D63)
    sse.py                     event stream endpoint
    static.py                  SPA + plugin assets
  cli/                         (11) typer app
  testing/                     the doubles (05 §Testing doubles, 13 §Fakes)
    mock.py                    MockAgent, StatsMockAgent, FakeStatsProvider: no subprocess
    fake_acp.py                the FakeACPAgent script: a real ACP subprocess, from a scenario
    scenarios.py               scenario(**kwargs) → the command line that runs one
  web/dist/                    built SPA, shipped as package data
web/                           SPA source (Vite + React + TypeScript), builds to athanore/web/dist
examples/                      user-land workflows (feature_build, gamedev, …) and adapters
docs/v1/                       these documents; docs/plans/ one plan per task of 17
tests/                         Python tests (13); web/e2e/ the Playwright suite
compose.yaml, docker/, scripts/  the dev stack: one image behind the gate, the app,
                               the SPA server and every agent (D64). Dev machinery —
                               nothing in athanore/ may depend on it, and driver/ is
                               athanore v0 driving this build (D67)
```

### Layering rule

Arrows point down only:

```
api, cli, plugins.builtin
        ↓
plugins.mount
        ↓
plugins.context
        ↓
engine, requests, agents, plugins.registry
        ↓
store, events, graph, settings, logging, plugins.decl
```

Peers within a tier may not import each other: each module in a tier is
an independent sibling, and the only cross-module imports allowed are
arrows down a tier. `graph` imports nothing from the package. `store`
never imports `engine`.
`agents` reaches the store only through `TaskContext` (which exposes
narrow services, not the store object — see 04). `graph` and
`plugins.decl` are joined above them, never in each other: `workflow.py`
imports both, because a declaration hangs on the workflow that carries
the graph, and `plugins.registry` imports both, because checking a
declaration means checking it against the graph's nodes. Nothing else
imports the two, and `graph` itself knows nothing about plugins, so the
pure layer stays pure. Enforced in CI with `import-linter`.

The plugin host (09) occupies three tiers of its own between `api` and
`engine`, and each is one direction of the same sentence: `mount` builds
routers out of contexts, `context` resolves a handler's scope out of the
engine and the store, `registry` validates declarations against the graph, and `decl` is
pure data — pydantic and nothing else — so it sits at the bottom beside
`graph`, which is what lets the two modules above join them. `mount` is the
one module with named arrows back up into `api`: a plugin route is an
operator route, so it hangs on `api.deps.operator_auth` and declares
`api.openapi`'s security requirement, and there is no lower place to put
a door that has to be the same one (D138).

`server.py` is the composition root and sits above the whole diagram: it
builds the store, the engine and the application and hands them to each
other, and nothing in the package imports it back. The one exception is
written to be no exception at all — `Workflow.run()`, 04 §Programmatic
host's one-workflow shorthand, imports `Server` *inside the method*, so
the module an author defines a workflow in never pulls uvicorn, the API
and the store in behind it.

The `api` layer needs two things from the engine at request time: the
live `TaskContext` of an in-flight task (to validate a submission against
the declared `output_model` and to check `ask_policy`) and the operator
operations. Both come from the `Engine` object passed to `create_app`
(`engine.live.context_for(task_id)`, `engine.ops`), never from module
globals.

### Public API (`athanore/__init__.py`)

```python
from athanore import (
    Workflow, Pool,                     # graph + capacity
    GraphError, NonRetryable,           # failure-policy exceptions (04)
    human_input, current_task, maybe_current_task,
    Agent, ACPAgent, AgentResult, AgentError,
    PluginContext, PluginError,         # plugin handlers (09)
    Server,                             # programmatic host (register + serve)
    __version__,
)
```

`AthanoreWorkflow`, `AthanoreAgent`, `AthanoreACPAgent` and `AthanoreServer`
remain as aliases for one minor version (14 §Compatibility). Every access
warns — the alias is never cached, so a second module that imports the old
name is told the same thing as the first — and none of them is in
`__all__`, because a deprecated name is one you had to type (D148).

## Library choices

| Concern | Choice | Why |
|---|---|---|
| Web framework | FastAPI 0.14x + uvicorn | Already the MVP's choice; pydantic-native; OpenAPI for free |
| Validation / schemas | pydantic v2 | Output models, action forms, settings, API schemas — one library |
| Settings | pydantic-settings (`ATHANORE_*`, `athanore.toml`) | Typed config, env + file precedence, documented defaults |
| SQL / migrations | SQLAlchemy 2.0 **Core** (async) + Alembic; aiosqlite / asyncpg | Typed table definitions, dialect-portable SQL, real migrations. Core, not the ORM: repositories return pydantic read models, so a session/identity-map layer would only add lazy-load and expiry traps (07) |
| SSE | `sse-starlette` | Correct keep-alive, disconnect handling, `Last-Event-ID` |
| HTTP client | httpx | Async + sync, used by CLI, tests, MockAgent |
| ACP | `agent-client-protocol` (Python SDK) | The protocol implementation the MVP verified against pi-acp and claude-agent-acp |
| MCP | `mcp` (Python SDK, streamable HTTP server) | The `mcp` tooling tier (05): the task tools as a server the agent harness connects to, mounted in the same FastAPI app |
| IDs | `python-ulid` | Sortable, URL-safe, no coordination |
| Logging | structlog (JSON in prod, pretty in dev) | Structured, contextual (run_id/task_id bound per attempt) |
| CLI | typer + rich | Argument parsing with help, tables, colors, low ceremony |
| Retries in clients | httpx transport `retries=` | Connection-level retries only, in the CLI; never in the engine (rule 3 owns retries) |
| Tests | pytest, pytest-asyncio, hypothesis (graph parsing), respx, freezegun, pytest-cov | See 13 |
| Lint / types | ruff, pyright (strict on `graph`, `engine`, `store`), import-linter; oxlint for the SPA, the linter its own scaffold ships (D77) | |
| Python | 3.11+; 3.13 in the dev stack and the CI default | `StrEnum` (events, error codes) and `asyncio.timeout` (the three nested timeouts of D60) are the floor; every runtime dependency already supports 3.11 (D66) |
| Packaging | uv, hatchling; `athanore[postgres]` extra | |
| Frontend | Vite, React 19, TypeScript strict, TanStack Router + Query, Tailwind v4, shadcn/ui, react-hook-form + zod, `@rjsf/core` + `@rjsf/shadcn` (JSON-Schema forms), cmdk, Phosphor icons, `@fontsource-variable/jetbrains-mono`, react-markdown + shiki (lazy), @tanstack/react-virtual, react-resizable-panels, `@xyflow/react` (React Flow, the graph pane's canvas), `@hey-api/openapi-ts` (client + TanStack Query options), Vitest + Testing Library + Playwright | See 10; the design mock's single-page dashboard |

Nothing in the core depends on pi, Claude, or Docker. Those live in
`examples/` (memory: vendor adapters are user-land).

## Request flows

### Submit a run

```
CLI/SPA ─POST /api/workflows/{wf}/runs {title, description}─▶ api.runs
  → engine.ops.submit(wf, title, description)
      uow: insert Run(status=queued, position=max+1)
           insert Task(node=start, status=ready, payload={title, description})
           outbox: run.created, task.enqueued
      commit → EventBus publishes → SSE
      scheduler.notify()
  ← 201 {run_id}
```

### Dispatch and execute an attempt

```
scheduler tick
  for each pool with free slots:
    uow: claim_ready(limit, workflows in pool) → tasks flip ready→in_progress (SELECT … FOR UPDATE / single-writer)
  for each claimed task: runner.run_attempt(task) as an asyncio.Task holding a pool lease
runner
  bind TaskContext (contextvar), publish task.started
  await node.fn(*edge_refs, **payload)
  interpret return → transitions (routing.py)
  uow: task done; enqueue successors; run completed if no pending; outbox events
  on exception: uow: task failed; retry or dead-letter; run failed; log entry
  finally: release lease, unbind context, scheduler.notify()
```

### Agent inside a body

```
await SomeACPAgent().run(prompt)
  ctx = current_task()  (task_id, token, api_base, services)
  declare output_model + ask_policy on ctx (for the duration)
  spawn subprocess, ACP initialize/new_session/config, prompt
  stream chunks → ctx.stream.append() (persisted in batches, published as task.stream)
  permission → requests.service.create(mode=options) … wait → answer → ACP
  agent curls: GET /api/tasks/{id}  POST …/log  POST …/submit  (task token)
  turn ends → repair loop if needed → attach submission → stats entry
```

### Human input

```
await human_input(prompt, options=…)
  requests.service.reopen_or_create(task, …)
  engine.pools.release(lease)          # waiting does not hold a slot
  await requests.service.wait(request_id)
  await engine.pools.readmit(lease)    # re-admit queue, served before new claims (04)
```

### Operator answers

```
SPA ─POST /api/requests/{id}/answer {option_id | value}─▶ api.requests
  → requests.service.answer(): validate mode, run validator, insert Answer
  → outbox request.answered → waiter wakes → SSE updates the inbox
```

## Concurrency model

- One asyncio event loop. The store is async (aiosqlite); no blocking DB
  calls on the loop. SQLite runs in WAL mode with `busy_timeout`; writes
  are serialized by the UnitOfWork (one writer connection).
- A UnitOfWork is short: it never spans an `await` on a node body, an
  agent, or a request wait. Bodies run outside any transaction; the
  runner opens one to record the outcome.
- Node bodies run as asyncio Tasks. CPU-heavy or blocking work in a body
  is the author's problem; `asyncio.to_thread` is available and documented.
- Agent subprocesses are owned by the attempt that spawned them and are
  terminated in the attempt's `finally`, on cancel, on move, on delete,
  and on server shutdown.
- The scheduler is the only consumer of the ready queue; claiming is
  transactional so a crash between claim and run leaves an in-progress
  row that recovery resets.

## Configuration

`AthanoreSettings` (pydantic-settings). Precedence: CLI flags > env
(`ATHANORE_*`) > `athanore.toml` in the root path > defaults.

| Setting | Default | Notes |
|---|---|---|
| `root_path` | cwd | Anchors db, state dir, default project dirs |
| `db_url` | `sqlite+aiosqlite:///{root}/athanore.db` | Or `postgresql+asyncpg://…` |
| `host` / `port` | `127.0.0.1` / `4002` | Loopback: no operator auth. Non-loopback: an operator token is required (12) |
| `public_url` | `http://{host}:{port}` | What agents are told; set for containers/remote agents |
| `operator_token` | unset | Only needed for a non-loopback `host`; `athanore token rotate` generates one (12) |
| `require_token` | false | Force operator auth even on loopback (a reverse proxy in front of a loopback bind) (12) |
| `body_limit` | 1 MiB | Request body cap, 413 beyond (08) |
| `sse_replay_cap` | 5000 | Max events replayed on reconnect before `resync` (08) |
| `workers` | 1 | Default pool capacity |
| `max_retries` | 3 | Global; per-node override in 04 |
| `agent_timeout` | 3h | Default per agent run |
| `permission_policy` | unset | Optional global override of the class default |
| `agent_command` | unset | Env/CLI only, never TOML: replaces every `ACPAgent.command` at spawn; for running examples on `FakeACPAgent` (05, 13) |
| `cors_origins` | [] | Dev only |
| `log_format` | `pretty` in TTY, `json` otherwise | |
| `stream_flush_interval` | 0.4s | Agent stream batching |
| `run_migrations` | true | `Server.start()` migrates before it serves; false leaves the schema to `athanore db upgrade` (11) |
| `forwarded_allow_ips` | unset | Passed to uvicorn: which proxies' `X-Forwarded-*` to trust (12 §Beyond the LAN) |
| `retention` | events 30d, stream chunks 14d | 07 |

Legacy names (`ARTIFICER_HOST`, `ARTIFICER_PORT`, `ARTIFICER_DB`) are read
with a deprecation warning for one minor version, and only when the
`ATHANORE_*` name is unset. `ARTIFICER_DB` was a filesystem path in v0, so
a bare path becomes `sqlite+aiosqlite:///{path}` (D72).

### `athanore.toml` layout

One file, three kinds of table. Top-level keys are settings from the
table above (snake_case, same names as the env variables without the
prefix); `[retention]` is the nested settings model; `[pools]` and
`[workflows]` are read by `athanore serve` (09 §Discovery, 11) and are
not settings, so `AthanoreSettings` ignores them.

```toml
host = "127.0.0.1"
port = 4002
workers = 2
max_retries = 3
log_format = "json"

[retention]
events_days = 30
stream_days = 14

[pools]
local = 1
cloud = 8

[workflows]
feature_build = { pool = "local" }
gamedev       = { pool = "local" }
msgtest       = { }                      # default pool
```

Unknown top-level keys are an error at startup (a typo must not silently
fall back to a default); unknown keys inside `[workflows.<name>]` are an
error too. `operator_token` and `agent_command` are refused in the file:
the first belongs in `.athanore/token` (12), the second is a test hook.

## Observability

- Every attempt binds `run_id`, `task_id`, `node`, `workflow`, `attempt` into
  structlog context; agent subprocess stderr is captured to the log at
  DEBUG with the same binding.
- `configure_logging` routes stdlib `logging` through structlog, and the
  server MUST build uvicorn with `log_config=None`. Uvicorn applies its
  own dictConfig from `Config.__init__` — not only from `uvicorn.run()` —
  which installs handlers on `uvicorn`, `uvicorn.error` and
  `uvicorn.access` and stops them propagating, putting two formats on one
  stderr.
- Events (07) are the business-level trail. Metrics are a later seam
  (`/api/health` already reports counts; Prometheus can be added without
  touching the engine).

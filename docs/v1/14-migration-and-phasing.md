# 14 — Migration and delivery plan

v1 is a rewrite of the package with the MVP as its behavioural spec. It
is delivered in phases that each leave a working system; the MVP's
example workflows and their tests are the acceptance harness throughout.

## Repository changes

| Today | v1 |
|---|---|
| `athanore/` flat modules | `athanore/{graph,engine,agents,requests,events,store,plugins,api,cli,testing,web}` (02) |
| `athanore/tui.py`, `athanore/web/templates`, textual deps | deleted |
| `workflow/` package at the root | `examples/` (feature_build, gamedev, msgtest, claude_acp, docker_acp, projects, pi stats provider) |
| `DESIGN.md`, `docs/design/*`, `docs/specs/*`, `docs/bugs/*` | kept as history; `docs/v1/` is the current design; `README.md` points here |
| `docker/`, `compose.yaml` | kept at the root as the dev stack (`docker/dev`, `scripts/`): one image behind the gate, the app and every agent, and `examples/docker_acp` dispatches into it through `./scripts/agent.sh` rather than building a second one (D64, D67) |
| `.gitignore` ignores `docs/design/*`, `docs/qa/*`, `docs/bugs/*` | The cited findings are folded into `docs/v1/20-carried-findings.md`, so `docs/v1` is self-contained (D59); whether to also un-ignore the history is open question 4 in 15. `docs/v1/` is tracked; add `.athanore/` (token file) and `athanore/web/dist/` (build output) to the ignore list |
| `pyproject.toml` deps: textual, netext | removed; added: sqlalchemy[asyncio], aiosqlite, alembic, sse-starlette, pydantic-settings, structlog, typer, python-ulid; extras `postgres` (asyncpg). `examples/` becomes a uv workspace member with its own extras |
| — | `web/` (Vite app), `pnpm-workspace.yaml`, build step copies to `athanore/web/dist`; hatch `artifacts = ["athanore/web/dist/**"]` so the ignored build output still ships in the wheel |

## Compatibility

- Python API: `AthanoreWorkflow`, `AthanoreACPAgent`, `AthanoreServer`,
  `AthanoreAgent` remain as deprecated aliases for one minor version;
  `wf.node(...)`, `human_input`, `current_task`, `Pool` keep their
  signatures. `template=` on agents is removed (inline prompts only).
- Wire API: v1 is a new contract (08). The one agent-facing change that
  affects prompts — header-only tokens — is invisible to agents because
  the façade writes the curl lines.
- Data: `athanore db import-v0` (07).
- Env: `ARTIFICER_*` read with a warning for one minor version.

## Phases

Each phase ends green on CI with the examples running on `FakeACPAgent`.

### Phase 0 — Scaffold (1 week)

Package layout, settings, structlog, ruff/pyright/import-linter, CI,
`web/` scaffold with shadcn and the neutral theme, OpenAPI → TypeScript
pipeline. The MVP code is moved under the new layout unchanged where it
can be (graph, routing rules) so tests keep running.

### Phase 1 — Store and engine (2 weeks)

SQLAlchemy Core tables, Alembic, repositories, UnitOfWork with outbox,
EventBus, v0 importer. Engine on the new store: scheduler with the
re-admit queue, pools with leases, claim-time tokens, runner with the
failure classes, ops, recovery. `waiting` status and slot release. Port
`test_graph`, `test_deterministic`, `test_fanout`, `test_priority`,
`test_worker_pools`, `test_pause`, `test_management`, `test_run_log`.

### Phase 2 — Requests and agents (2 weeks)

Requests service on the new tables; `human_input`; ACP façade split
(`base`, `acp`, `policies`, `submissions`, `stats`); `SessionStatsProvider`
with the pi provider in `examples/`; `FakeACPAgent`. Port `test_requests`,
`test_permissions`, `test_elicitation`, `test_ask`, `test_submissions`,
`test_acp_stats`, `test_stats*`, `test_agents`.

### Phase 3 — API and plugin manifest (1.5 weeks)

Routers (operator and `/api/agent/`), loopback-vs-network auth
dependency with `require_token`, error model, SSE, body-limit
middleware, OpenAPI snapshot. Plugin declarations, registry, and the
manifest endpoint with the `panel` kinds (09 phasing step 1), so the SPA
phase starts with the pane vocabulary it renders. Port
`test_api_surface`, `test_e2e`, `test_edit_run`. CLI on typer against the
new API (`test_cli_entry`).

### Phase 4 — SPA core (3 weeks)

Pane host driven by the manifest from the first commit, with the
builtins (overview, log, agent, graph, requests) declared through it;
Runs list, Inbox, Workflows, Settings, token screen; SSE invalidation;
command palette; RJSF `ActionForm` for form requests; Playwright suite
covering the TUI behaviours listed in 01. Served from the package. Built
directly on the imported design (`docs/v1/design/`): the token mapping
in 10 §Design system is the first commit of the phase.

### Phase 5 — Plugin actions, assets, discovery (1.5 weeks)

`route` + `action` wired to `ActionForm`; `assets` + `custom` +
`window.athanore`; entry-point discovery; `athanore serve`;
`athanore.toml` pools.

### Phase 6 — Examples, docs, release (1 week)

Port `examples/`, live smoke against pi and Claude ACP adapters, README,
`docs/v1` final pass, delete the TUI, tag 1.0.0.

## Risks

| Risk | Mitigation |
|---|---|
| Embedded uvicorn + asyncio store lifecycle in tests (the MVP's "fiddly part") | Keep the MVP's `_QuietUvicorn` pattern; `Server.start()/stop()` as awaitables; one fixture |
| The rail-list graph has no design for fan-out | Indented sub-lists per branch (10 §Graph pane); prototype against `gamedev` and `feature_build` fan-outs early in phase 4 |
| SSE behind proxies (buffering) | `X-Accel-Buffering: no`, keep-alives, documented proxy config |
| Slot re-acquisition after waiting changes dispatch semantics | Resumed tasks re-admit ahead of new work in their pool; tests for `workers=1` with a waiting run and a new run |
| The mock's inline styles do not translate one-to-one to shadcn | The component mapping table in 10 names a shadcn primitive per mock element; custom grids where the mock is denser than `Table` |

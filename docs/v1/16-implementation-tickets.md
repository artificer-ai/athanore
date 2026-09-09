# 16 — Implementation tickets

The delivery plan in 14, cut into tickets. Each ticket is one PR-sized
unit with a definition of done (13 §Definition of done applies to all:
tests at the lowest layer, OpenAPI snapshot updated if the wire changes,
decision recorded in 15 if a choice was made). "Spec" points at the
section that is the acceptance criterion. Dependencies are by ticket id;
tickets without one inside a phase can run in parallel.

Sizing: S ≤ 1 day, M 2–3 days, L 4–5 days.

## Epic 0 — Scaffold (Phase 0)

| Id | Ticket | Size | Spec | Depends |
|---|---|---|---|---|
| A0.1 | Package layout: create `athanore/{graph,engine,agents,requests,events,store,plugins,api,cli,testing}` packages; move `graph.py` → `graph/builder.py` + `model.py` + `validate.py` unchanged; `athanore/workflow.py` holding `Workflow` | M | 02 §Package layout, D48 | |
| A0.2 | `AthanoreSettings` (pydantic-settings): every key in 02 §Configuration incl. `require_token`, `body_limit`, `sse_replay_cap`; TOML + env + CLI precedence; `ARTIFICER_*` deprecation shim | S | 02 §Configuration | |
| A0.3 | structlog setup: pretty/json by TTY, `run_id/task_id/node/workflow/attempt` binding helpers | S | 02 §Observability | |
| A0.4 | Tooling: ruff, pyright (strict on graph/engine/store), import-linter contracts for 02 §Layering rule, uv workspace with `examples/` member, `postgres` extra | S | 02, 14 | A0.1 |
| A0.5 | CI workflow: `uv sync`, lint, typecheck, import-linter, pytest; nightly Postgres job stub | S | 13 §CI | A0.4 |
| A0.6 | `web/` scaffold: Vite + React 19 + TS strict + Tailwind v4 + shadcn init; `theme.css` generated from `design/nocturne.css`; fontsource JetBrains Mono; build copies to `athanore/web/dist`; hatch `artifacts`; `.gitignore` additions (`.athanore/`, `athanore/web/dist/`) | M | 10 §Design system, 14 | |
| A0.7 | OpenAPI → TS pipeline: `@hey-api/openapi-ts` config with the TanStack Query plugin, `pnpm gen` script, CI check that generated code is fresh | S | 08 §OpenAPI, 13 §Contract tests | A0.6 |

## Epic 1 — Store and engine (Phase 1)

| Id | Ticket | Size | Spec | Depends |
|---|---|---|---|---|
| A1.1 | SQLAlchemy Core tables for the full 07 schema (incl. `tasks.stats`, `requests.ordinal`, no `run_position`), async engine factory with the SQLite PRAGMAs, Alembic env + initial migration | M | 07 §Schema, D45 | A0.1 |
| A1.2 | UnitOfWork with outbox + EventBus: `emit()` in-transaction, insert on commit, publish after commit; single-writer lock; ephemeral `publish()` path for `task.stream` | M | 07 §Unit of work, 03 §Event, D40 | A1.1 |
| A1.3 | Repositories returning pydantic rows: RunRepo, TaskRepo, LogRepo, SubmissionRepo, StreamRepo, RequestRepo, EventRepo; grouped aggregate query for `RunSummary` | L | 07 §Repositories | A1.1 |
| A1.4 | `TaskRepo.claim_ready`: ordering SQL of 04, token minting at claim (hash stored, clear text returned), `queued → running` flip with `run.started`; Postgres `SKIP LOCKED` variant | M | 04 §Dispatch order, D38, D41 | A1.3 |
| A1.5 | Cascade-delete and retention job (stream chunks 14 d, events 30 d except `run.*`), `freezegun` tests | S | 07 §Retention | A1.3 |
| A1.6 | v0 importer `store/legacy.py` with the 07 mapping table; fixture databases from the MVP; idempotency test | M | 07 §Importing a v0 database | A1.3 |
| A1.7 | Event vocabulary enum (`events/names.py`) and the "every emitted name is in the enum" test | S | 03 §Event vocabulary | A1.2 |
| A1.8 | Engine: pools + leases, scheduler loop with the per-pool re-admit queue, `engine.live` registry | M | 04 §Scheduling, §Waiting, D43 | A1.4 |
| A1.9 | Runner: attempt lifecycle, routing interpretation, failure classes (`GraphError`, `NonRetryable`), retry/dead-letter, node `timeout` with clock paused while waiting, `CancelledError` handling | L | 04 §Running an attempt, §Failure classes, D42 | A1.8 |
| A1.9b | Fan-in: `join=True` node option and finalize check, branch frames on enqueue, `JoinRepo` + `join_arrivals`, arrival/dispatch in the runner's transaction, `join_incomplete` at quiescence, `output` shape rule, ops guards (`move` 409, `rerun` of a join) | M | 04 §Fan-in, D62 | A1.9 |
| A1.10 | `TaskContext` / `TaskServices` (log, stream, submissions, requests, run, events) and `current_task()`; stream flusher | M | 04 §TaskContext, 07 §Transcript writes | A1.9 |
| A1.11 | `engine.ops`: submit, edit, reorder, pause, resume, cancel, delete, rerun, retry, move, set_status; each transactional + event + notify | L | 04 §Operator operations | A1.9 |
| A1.12 | Recovery on startup (in_progress/waiting → ready, token cleared, unregistered runs flagged) | S | 04 §Recovery | A1.11 |
| A1.13 | `Server` programmatic host: `register(wf, pool)` with the registration-time name checks, `start()/stop()/serve()`, `wf.run()` shorthand | M | 04 §Programmatic host | A1.11 |
| A1.14 | Port engine tests: `test_graph`, `test_deterministic`, `test_fanout`, `test_priority`, `test_worker_pools`, `test_pause`, `test_management`, `test_run_log`; new tests for waiting-releases-slot and re-admit ordering under `workers=1`; hypothesis suite for graph parsing | L | 13 §Pyramid | A1.13 |

## Epic 2 — Requests and agents (Phase 2)

| Id | Ticket | Size | Spec | Depends |
|---|---|---|---|---|
| A2.1 | Requests service: create/answer/wait/poll, validators (pydantic + light JSON-schema), landing-point validation and error classes, EventBus wake-ups with the missed-wake guard | L | 06 §Service | A1.10 |
| A2.2 | `human_input` with ordinal reopen/replay, lease release/re-admit, timeouts; crash-replay tests (three questions, die after two) | M | 06 §Restart durability, 04 §Waiting, D44 | A2.1 |
| A2.3 | Agent façade split: `base.py` (Agent, AgentResult, prompt assembly with `/api/agent/` curl lines, kickoff), `submissions.py` (declare/attach/repair) | M | 05 §Agent classes, §Prompt assembly, §Submissions | A1.10 |
| A2.4 | `ACPClient` + `ACPAgent.run()` lifecycle: spawn with env scrub/allowlist + task env vars, initialize/new_session/config-by-category, streaming to `StreamChunk` kinds incl. `thought`, repair loop, outcome mapping, `finally` cleanup | L | 05 §The ACP client, §Session lifecycle | A2.3 |
| A2.5 | Policies: permission (by kind, timeouts, engine-authored answers), elicitation bridge (form mode, URL declined), HTTP ask gating | M | 05 §Policies, 06 | A2.1, A2.4 |
| A2.6 | Stats: `SessionStatsProvider` protocol, ACP `usage` merge, entry recorded once per exit path to log line + `agent.stats` + `tasks.stats` | M | 05 §Stats entry, D27, D46 | A2.4 |
| A2.7 | `athanore.testing`: `MockAgent`, `StatsMockAgent`, `FakeACPAgent` subprocess driven by JSON scenarios (reject-first option order, elicitation, usage, stop reasons), `FakeStatsProvider` | L | 13 §Fakes | A2.4 |
| A2.8 | `examples/pi/stats.py`: the MVP session-file parser as a provider, with its tests moved | S | 05 §Truncation detection | A2.6 |
| A2.10 | Tooling tiers in the façade: `tooling` attribute, `auto` from `initialize` capabilities, `mcp_servers` on `new_session`, tier-specific kickoff blocks, athanore tool server auto-allowed under `ask` | M | 05 §Tooling tiers, 19, D63 | A2.4, A3.4b |
| A2.11 | pi extension `examples/pi/extensions/athanore.ts` registering the four tools over HTTP; pi example agents set `tooling="native"` | S | 05 §Tooling tiers | A2.10 |
| A2.9 | Port tests: `test_requests`, `test_permissions`, `test_elicitation`, `test_ask`, `test_submissions`, `test_acp_stats`, `test_stats*`, `test_agents` | L | 13 | A2.7 |

## Epic 3 — API, CLI, plugin manifest (Phase 3)

| Id | Ticket | Size | Spec | Depends |
|---|---|---|---|---|
| A3.1 | `create_app`, error model (`ApiError` → `{error, code}` with the code enum), 422 shape, body-limit middleware (413) | M | 08 §Conventions, §Sizes | A1.13 |
| A3.2 | Auth dependencies: loopback detection by bind host, `require_token`, operator bearer, task token (`hmac.compare_digest` on hash, attempt-scoped), `/api/me` | M | 08 §Authentication, 12, D47 | A3.1 |
| A3.3 | Operator routers: workflows (+ `/source`), runs (incl. `/graph`, `/position`, `/log`, `/events`, `/requests`), tasks (`/stream`, retry/move/status), requests (inbox, answer → `RequestView`) | L | 08 §Endpoints | A3.2, A1.11, A2.1 |
| A3.4 | Agent router under `/api/agent/`: task read, log, submit (validate via `engine.live`), ask, long-poll | M | 08 §Agent-facing, D39 | A3.2, A2.5 |
| A3.4b | MCP server at `/mcp/agent` (`mcp` SDK streamable HTTP, mounted sub-app, task-token auth), the five tools with `submit_result`'s schema from the live context, MCP-client tests | M | 08 §MCP, D63 | A3.4 |
| A3.5 | SSE endpoint on `sse-starlette`: replay by cursor with `sse_replay_cap` + `resync`, live fan-out, `names` glob filter, `run` filter, ephemeral events without `id:`, `?access_token=` | M | 08 §Events | A3.2, A1.2 |
| A3.6 | Static hosting of the SPA and plugin assets with the CSP header | S | 08, 12 §Plugins | A3.1 |
| A3.7 | OpenAPI: tags, security schemes, typed models everywhere, snapshot test | S | 08 §OpenAPI, 13 §Contract tests | A3.4, A3.5 |
| A3.8 | Plugin declarations + registry + validation (`route`, `action`, `panel` as a call, `on`), `PluginContext` as a FastAPI dependency, manifest endpoint, `on` dispatch after commit | L | 09 §Declarations, §Registration, §Wire contract, D50 | A3.3 |
| A3.9 | Builtin plugin declarations (`overview`, `log`, `agent`, `requests`, `graph`) in `plugins/builtin/` with their `source` routes | M | 09 §Builtins are plugins | A3.8 |
| A3.10 | CLI on typer: serve (discovery, toml pools, migrations, `--open`), db verbs, token verbs, login, all client verbs with `--json`, exit codes, bare-workflow alias | L | 11 | A3.7 |
| A3.11 | Port `test_api_surface`, `test_e2e`, `test_edit_run`, `test_cli_entry`; auth matrix tests; SSE replay/live tests | L | 13 | A3.10 |

## Epic 4 — SPA core (Phase 4)

| Id | Ticket | Size | Spec | Depends |
|---|---|---|---|---|
| A4.1 | App shell: TanStack Router single route with `?run=&pane=`, zustand persisted prefs, header/list/detail/footer layout, splitter, list collapse | L | 10 §Layout | A0.6, A0.7 |
| A4.2 | SSE wrapper (`Last-Event-ID`, reconnect, `started_at` manifest refetch) + invalidation table with exact-before-glob matching and 250 ms coalescing; server-down banner | M | 10 §Realtime and caching | A4.1, A3.5 |
| A4.3 | Run list grid with status pills, NODE cell + `⚠`, workflow chips, `/` filter | M | 10 §Layout, §Attention | A4.2 |
| A4.4 | Pane host driven by the manifest: cycle order, dots, index clamp, `PaneRenderer` for `markdown/kv/table/log/chart/dashboard/form/custom/placeholder` | L | 10 §Panes, 09 §Panel kinds | A4.2, A3.9 |
| A4.5 | Builtin renderers: overview (metric tiles, node bars, kv, NODES table, cards slot), log pane with composer, agent stream with virtualised blocks and chunk-kind mapping, requests pane, graph rail list with loop rails and fan-out sub-lists | L | 10 §Panes, §Graph pane | A4.4 |
| A4.6 | Docked request panel + `ActionForm` on RJSF/shadcn (options by kind, text, form; 422 → `extraErrors`); inbox as the global pane | M | 10 §Plugin renderers, 06 §SPA, D49 | A4.5 |
| A4.7 | Overlays: command palette (cmdk), new run (POSITION top/bottom), workflow library with source viewer, edit run, pickers, keys, task drawer | L | 10 §Overlays | A4.4 |
| A4.8 | Keyboard map incl. `D` delete, focus scoping, suppression in inputs | S | 10 §Keyboard, D51 | A4.7 |
| A4.9 | Token screen and 401 handling for network binds | S | 10 §Auth in the browser | A4.1 |
| A4.10 | Vitest suites (renderers, ActionForm nested schemas, invalidation table, SSE wrapper) and Playwright E2E on `FakeACPAgent` (submit → permission → human_input → complete; reorder; pause/resume; server-down; shortcuts; inbox); Lighthouse a11y gate | L | 13 §Pyramid | A4.8 |

## Epic 5 — Plugin actions, assets, discovery (Phase 5)

| Id | Ticket | Size | Spec | Depends |
|---|---|---|---|---|
| A5.1 | Action execution endpoint with scope resolution, `PluginError`, `confirm` dialog and `form` panel kind wired to `ActionForm` | M | 09 §Wire contract | A3.8, A4.6 |
| A5.2 | Assets: manifest listing, `StaticFiles` mount, `CustomElementHost`, `window.athanore` (fetch, subscribe, theme tokens) | M | 09 §Escape hatch | A4.4 |
| A5.3 | Entry-point discovery, `athanore.toml` `[pools]` / `[workflows]`, precedence vs programmatic registration | S | 09 §Discovery, 11 | A3.10 |
| A5.4 | Plugin test workflow with one of each declaration; scoping/404, validation, liveness, `on` handler tests | M | 13 §Pyramid (Plugins) | A5.2 |

## Epic 6 — Examples, docs, release (Phase 6)

| Id | Ticket | Size | Spec | Depends |
|---|---|---|---|---|
| A6.1 | Port `examples/` (feature_build, gamedev, msgtest, claude_acp, docker_acp, projects) to the v1 API with pinned adapter versions. (No `examples/docker`: `docker/dev` is the one image and `scripts/agent.sh` the one way in, D64/D188) | M | 05 §User-land adapters, 14 | A5.3 |
| A6.2 | Live smoke scripts (`ATHANORE_SMOKE=1`) against pi and Claude ACP | S | 13 §Live smoke | A6.1 |
| A6.3 | README rewrite pointing at `docs/v1`; `DESIGN.md` banner; deprecated aliases with warnings; `docs/v1` staleness pass. (No TUI, `web/templates` or textual deps to delete — none of them live here, D65) | S | 14 §Compatibility | A6.1 |
| A6.4 | `pip-audit` / `pnpm audit` in CI, coverage gates, final `docs/v1` pass, tag 1.0.0 | S | 13 §CI | A6.3 |

## Cross-cutting decisions still open (15 §Open questions)

Resolve before the ticket that needs them: open question 4 (git-ignored
design history) before A0.1; open question 5 (run retention) can wait
for 1.x.

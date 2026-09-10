# 01 — Vision, principles, and the MVP feature inventory

## What Athanore is

Athanore is an orchestrator for multi-stage AI agent pipelines where **the
graph is code and the code is in charge**. A workflow author writes a
Python module: each stage is an `async def` decorated as a node, the
stage's successors are its parameters, and the stage's return value picks
the next stage. Inside a stage the author may await an agent (any ACP
agent: pi, Claude Code, a container, a stub), run deterministic Python
(tests, linters, git), or ask a human. The engine runs many concurrent
runs of many workflows under explicit capacity limits, persists
everything, and exposes it to an operator UI.

The product bet, unchanged from the MVP: **agents produce values,
deterministic code makes decisions.** An agent never moves a task; it
submits a validated value and the node body routes on it. Every edge a run
traverses is code you can read, test, and blame.

## The three rules (unchanged)

These are the whole authoring interface. v1 adds capability only by
attaching it to these seams, never by adding a fourth rule.

1. **The signature is the graph.** Positional parameters are edges to other
   nodes. A keyword-only parameter after `*` is the optional payload.
   Exactly one node is `start=True`.
2. **The return value is the routing.** Plain value + one successor →
   auto-transition. Edge ref (`return qa`) or called edge ref
   (`return qa(payload)`) → explicit transition. List of refs → fan-out.
   No successors → the branch completes; the run completes when its last
   branch lands.
3. **The exception is the failure policy.** Raising fails the attempt; the
   engine applies retry then dead-letter.

A node declared `join=True` closes a fan-out: it runs once, after every
branch of that fan-out has transitioned into it, with the branch values
as its payload (04 §Fan-in). That is node metadata on the existing seam,
not a fourth rule: branches still route by return value, and the join is
reached the same way as any other successor.

Everything else (agents, human input, plugins, pools, priorities) is
metadata on the workflow or an object awaited inside a body.

## Design principles for v1

- **Small core, everything else a plugin.** Core = graph, engine, store,
  requests, events, API host, plugin host. The built-in operator views are
  plugins shipped in the same package, so the plugin API is proven by
  dogfooding.
- **Web native frontend.** A real SPA with a real component library. No
  Python-to-DOM layer. Python describes UI as data; the browser draws.
- **One wire contract.** The HTTP + SSE API is the only way in. The SPA,
  the CLI, agents (`curl`), and plugins all use it. OpenAPI is generated
  from the code and a typed client is generated from OpenAPI.
- **Local first.** Athanore runs on the operator's own machine. Loopback
  is the default, nothing asks for a login there, and the only credential
  in play is the per-task token that scopes an agent to its own task.
  Binding to a network is a deliberate choice that turns on an operator
  token.
- **Durable by default.** Every state change is a transaction; every
  transaction that matters emits an event; the event log is the audit
  trail and the realtime feed.
- **Boring where it can be.** SQLite, FastAPI, React, shadcn. Named
  libraries are chosen for longevity and documentation, not novelty.
- **Real data only.** Stats and status never zero-fill or estimate.
  Unknown is omitted (carried from the MVP's stats spec).

## MVP feature inventory (what v1 MUST preserve)

Derived from the MVP code and its 200+ tests. Each row names where v1
specifies it.

### Engine

| Feature | v1 doc |
|---|---|
| Graph DSL: edges from parameters, payload after `*`, `/` form accepted, one start node | 04 |
| Finalization validation: unknown edge, duplicate node, unreachable node, start count | 04 |
| Generations (BFS depth, first reach for cycles) → default priority `-generation` | 04 |
| Routing interpretation: bare ref, called ref, list (fan-out), plain value, terminal | 04 |
| Fan-out branches; run completes when the last branch lands | 04 |
| Fan-in: `join=True` nodes collect every branch of a fan-out (new in v1) | 04 |
| Loop-backs (review → engineering) with payload carried or dropped | 04 |
| Deterministic nodes with no agent (test gate) | 04 |
| Retries with cap, dead-letter, run failed; retries keep created timestamp | 04 |
| Restart recovery: orphaned in-progress → ready | 04 |
| Dispatch order: run position, explicit node priority, downstream-first, newest-first | 04 |
| Named capacity pools; default pool sized by `workers`; capacity 0 parks; strict reservation | 04 |
| Pause / resume (in-flight task finishes, next is blocked) | 04 |
| Cancel run (terminates in-flight agents), delete run | 04 |
| Rerun node, retry task, move task, set task status; failed run returns to running | 04 |
| Edit run title/description; reorder / swap run positions | 03, 08 |
| Work log: append-only, attributed (node, author ∈ agent/engine/user) | 03 |
| Engine log entries on failure and per-agent-run `[stats]` lines | 05 |
| `current_task()` / `maybe_current_task()` context for bodies | 04 |

### Agents

| Feature | v1 doc |
|---|---|
| Agent as a class: `system_prompt`, `model`, `thinking`, `output_model`, `command`, `cwd`, `env`, `timeout` | 05 |
| ACP session lifecycle: initialize, new session, config options by category, prompt, close | 05 |
| Kickoff block injected into prompts (task read, log append, submit, ask) | 05 |
| Structured submissions validated at the endpoint (422 + errors + schema); last valid wins | 05, 08 |
| In-session repair turns when a turn ends without a valid submission | 05 |
| Stop-reason handling (refusal, cancelled), max-output-token truncation detection | 05 |
| Agent output stream persisted and live (`agent_progress`) | 05, 07 |
| Permission policy `ask` (default) / `auto_allow` / `auto_deny`, timeouts, option chosen by kind | 05, 06 |
| Elicitation bridged as a form request; URL mode declined | 05, 06 |
| HTTP ask (opt-in per agent class) with bounded long-poll | 05, 06, 08 |
| Env scrubbing of session-scoped variables; explicit env overrides | 05, 12 |
| Stats: tokens, cost, model, tool calls, duration, session id, repairs; real data only | 05 |
| `MockAgent` / `StatsMockAgent` test doubles; fake ACP agent process | 13 |
| User-land adapters (Claude ACP, Docker sandbox) as examples, not shipped in the package | 05 |

### Human in the loop

| Feature | v1 doc |
|---|---|
| `human_input(prompt)`, `options=[...]`, `output_model=M` | 06 |
| One request object for permissions, elicitations, node questions, HTTP asks | 06 |
| Keyed answers (no FIFO, no cross-talk between fan-out branches) | 06 |
| Answer validation at the landing point; 409 once answered; validator re-registration | 06 |
| Restart durability: waiter re-attaches to an open request | 06 |
| Pending-request counts per run (attention glyph) | 06, 08 |

### Server, API, CLI, UI

| Feature | v1 doc |
|---|---|
| Register many workflows in one process; `wf.run()` shorthand | 04, 11 |
| Health, workflows (graph + pool stats), runs list/detail/events, requests, answers | 08 |
| Operator log append; task-token endpoints (read task, log, submit, ask, wait) | 08 |
| OpenAPI docs | 08 |
| CLI: submit, ls, run, logs, workflows, requests/answer/permit/deny, pause/resume/cancel/rm/rerun/retry/move/set-status | 11 |
| Operator UI: runs list with status/node/attention marker; run overview, work log, live agent stream, graph diagram with node states; new run; edit run; append log; task pickers (retry/move/cancel); reorder; pause/resume; requests panel with per-option buttons, text box, form; auto-focus on new request; server-down state | 10 |
| Serve the UI from the server process | 02, 10 |

### Example adapters (user-land, kept as examples)

`claude_acp`, `docker_acp` and the `pi` package. They are the vendor half
of 02 §Small core — nothing in `athanore/` may know about pi, Claude or
Docker, so the adapters that do live here — and they remain the
integration test bed (`examples/tests`).

`feature_build`, `gamedev`, `msgtest` and `projects` were ported in the
migration and have since been removed (D212). They were showcases rather
than adapters: nothing in `athanore/` depended on them, and the shape they
demonstrated is better shown by `workflows/feature`, which is a real
seat rather than a sketch of one. `examples/` is read on GitHub as
documentation; `athanore-examples` is not published.

## What v1 adds

- A browser SPA replaces the Textual TUI (the TUI is deleted, not kept).
- Plugin system: workflows declare routes, actions, panels, and event
  handlers; optional static web components.
- An opt-in operator token for network binds; task tokens no longer
  leak through operator responses.
- Server-sent events replace polling.
- SQLAlchemy + Alembic storage with a real migration path and retention.
- Waiting on a human releases the worker slot.
- Per-node overrides for retries and timeouts on the existing metadata seam.
- Failure classes on rule 3: `GraphError` and `NonRetryable` dead-letter
  at once instead of burning retries.
- Structured logging and a settings object.
- Workflow discovery via entry points and `athanore serve`.

## Non-goals for v1

- Multi-user accounts, roles, or SSO. One operator identity (a shared
  token). The auth layer is a seam for later.
- Distributed workers. One server process owns one store.
- Agent-authoritative task movement (dropped permanently, not deferred).
- A Python DSL that emits UI components. Plugins describe data; custom UI
  is a web component.
- Two-phase suspended nodes (persist the wait, re-dispatch on answer).
  Re-execute-and-reattach stays the durability posture; see 04.
- A Textual renderer for the plugin manifest.

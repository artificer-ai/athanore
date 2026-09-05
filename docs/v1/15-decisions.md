# 15 — Decision log

Carried decisions come from `DESIGN.md` and `docs/design/*`; new ones are
marked. Each has a reason; reversing one means editing this table.

| # | Decision | Status | Reason |
|---|---|---|---|
| D1 | The three rules are the whole authoring interface; capability attaches to existing seams (workflow metadata, awaited objects, return values, exceptions) | carried | The usual way projects like this die is a fourth rule |
| D2 | Agents produce values; deterministic code routes. Agent-driven task movement is dropped, not deferred | carried | Every edge must be readable, testable, blameable |
| D3 | Native engine; "queue per node" is a query; the engine does not know agents exist | carried | Simplicity; agents are a capability of bodies |
| D4 | State flows through the append-only work log, payloads only for branch identity | carried | Concurrency-safe primitive; agents pull context themselves |
| D5 | Structured submissions validated at the endpoint (422 + schema), last valid wins, in-session repair turns | carried | Agent self-corrects in the same session; engine retry is the expensive path |
| D6 | Durability posture: re-execute the attempt after a crash; `human_input` re-attaches | carried | Two-phase suspension only if it hurts |
| D7 | Dispatch order: run position, explicit node priority, downstream-first, newest-first; retries keep `created` | carried | Under scarce inference an in-flight run drains before a new one starts |
| D8 | Named capacity pools, strict reservation, backend-agnostic, names reserved at registration | carried | Pools express a budget the operator knows; the scheduler never knows models |
| D9 | One request object for permissions, elicitations, node questions, HTTP asks; keyed answers; validation at the landing point | carried | One attention surface; no cross-talk under fan-out |
| D10 | Permission options chosen by kind, never by index; `ask` is the default policy; policies that cannot be honoured fail loudly | carried | claude-acp lists reject first; a silent denial reported `ok` |
| D11 | Config options resolved by category from what the session advertises; rejections logged | carried | Ids differ per agent; silent swallows hid a no-op |
| D12 | Plugins: declarations cross the wire, renderers do not; workflow is the host; actions allowed; escape hatch is a web component; explicit `ctx`; builtins dogfood; unknown kinds degrade | carried | Web-native frontend and a small core at once |
| D13 | The Textual TUI is deleted; the SPA is the operator UI; the CLI stays small | carried (plugins.md), executed | One frontend to maintain; the manifest is frontend-agnostic if a TUI ever returns |
| D14 | Vendor-specific adapters (pi, Claude, Docker) and stats parsing live in `examples/`, not the package | carried (memory) | Shipped library stays minimal |
| D15 | Waiting on a human releases the pool slot; resumed tasks re-admit ahead of new work | **new** | One unanswered question stalled the whole server under `workers=1` |
| D16 | Local first: loopback default with no operator auth; an operator token only when bound to a network; task tokens hashed, header-only, never returned in operator responses | **new** | Athanore runs on the operator's own machine; the cheap fixes (no token leak, header-only) cost nothing, the heavy ones stay opt-in |
| D17 | SQLAlchemy 2 async + Alembic; SQLite default, Postgres optional; cascade deletes | **new** | Hand-rolled migrations and blocking I/O on the loop do not scale past the MVP |
| D18 | Events are the audit trail and the realtime feed (outbox in the same transaction; SSE replays by cursor) | **new** | Store and feed can never disagree; late joiners catch up |
| D19 | Agent transcript is its own table with retention, not events | **new** | 2–3 events/s per task with no retention was unbounded growth |
| D20 | Per-node `retries` and `timeout` on the node-options seam | **new** | Requested repeatedly; same seam as `priority` |
| D21 | 422 for validation, stable error codes, ISO timestamps, ULID run ids | **new** | v1 is a new wire contract; parity with the MVP's ad-hoc 400s is not worth carrying |
| D22 | `queued` run status and `waiting` task status | **new** | Operators could not see "waiting for a slot" or "waiting for me" from the status alone |
| D23 | Run list order is `position`, not `priority` | **new** | Two things called priority (run and node) confused every reader |
| D24 | Frontend: Vite/React/TS, TanStack Router + Query, shadcn on Tailwind v4, cmdk, generated OpenAPI client (D49 names the generator) | **new** | Mainstream, documented, typed end to end; user preference for React + shadcn |
| D25 | Design tokens come from the Claude Design "Nocturne" system, imported to `docs/v1/design/` | **new** | Imported 2026-09-05; the mapping is in 10 §Design system |
| D26 | CLI on typer + rich with `--json` everywhere; `athanore serve` with entry-point discovery | **new** | Composable, discoverable; replaces `python -m workflow` |
| D27 | Truncation detection and token/cost stats go through a `SessionStatsProvider`; the pi session-file reader is an example | **new** | The core read pi's home directory; that is an adapter concern |
| D28 | Body size limit; rate limiting is a later seam | **new** | A runaway agent must not fill the disk; throttling is not worth its complexity on one machine |
| D29 | One process, one store, one bus in v1 | **new (explicit)** | Every internal boundary is an interface; distribution is a later seam |
| D30 | `template=` prompt files removed | **new** | Superseded by inlined prompts (spec `inline-prompts.md`); only tests used it |
| D31 | The SPA keeps the TUI's single-page shape from the design mock: run list left, one cycling pane right, overlays for everything else; no multi-page IA | **new** | The mock is the product owner's design; the TUI shape is what operators already know |
| D32 | The graph pane is the mock's vertical rail list, not a React Flow canvas; fan-out renders as indented sub-lists | **new** | Simpler, denser, and matches the mock; pipelines are mostly linear with loop-backs |
| D33 | The mock's `messages` pane (node → node) becomes the `requests` pane (human-in-the-loop history) | **new** | Athanore has no node-to-node messages; the work log is that channel; requests are the thing operators need to see |
| D34 | The mock's 1–10 priority slider on New Run becomes a top/bottom POSITION choice | **new** | Run ordering is a list position (D23), not a numeric priority |
| D35 | The mock's "hot-reloaded from workflows/" library is served from `GET /api/workflows/{name}/source`; hot reload is a later seam | **new** | Restart-to-reload is fine for v1; the source viewer is the valuable part |
| D36 | CRT chrome (scanlines, scan band, vignette, flicker) ships on by default per the mock, off under reduced motion, toggleable in settings | **new** | It is the mock's signature; accessibility keeps the override |
| D37 | Design tokens are the Nocturne sheet with the mock's app overrides (JetBrains Mono, 12px, 2px radii, status colours); no light theme in v1 | **new** | The mock defines one dark theme; a light theme is a token-file change later |
| D38 | Task tokens are minted at claim, per attempt, hash-only at rest | **new (review 2026-09-05)** | Minting at enqueue with hash-only storage loses the clear text before the claim; per-attempt tokens also make recovered/retried attempts unforgeable from a dead one |
| D39 | Agent-facing routes live under `/api/agent/` on their own router | **new (review)** | One path with two response shapes chosen by credential is not expressible in OpenAPI and overloads the auth dependency |
| D40 | `task.stream` is an ephemeral bus/SSE event, never stored; the MVP's `transition` event folds into `task.enqueued` | **new (review)** | D19 moved the transcript out of `events` but still wrote one cursor event per flush; that kept most of the growth |
| D41 | Dispatch reads `runs.position` through the join; no `run_position` snapshot on tasks | **new (review)** | The claim query already joins `runs`; the snapshot and its reorder sync were legacy |
| D42 | Failure classes on rule 3: `GraphError` and `NonRetryable` dead-letter on the first attempt; everything else retries | **new (review)** | Retrying a routing defect burns inference; the exception type is metadata, not a fourth rule |
| D43 | Waiting tasks resume through a per-pool re-admit queue served before store claims; the node timeout clock pauses while waiting | **new (review)** | "Re-admit ahead of new work" needed a mechanism, since a `waiting` row is not `ready`; a day-long human wait must not fail a ten-minute agent cap |
| D44 | Node requests carry an ordinal per task row; a recovered body replays earlier answers | **new (review)** | The MVP re-attached only to the open request and re-asked every earlier one after a crash |
| D45 | SQLAlchemy Core, not the ORM; repositories return pydantic rows | **new (review)** | The design already forbade ORM instances crossing a boundary; the session/identity map then only adds traps |
| D46 | Agent stats are stored on `tasks.stats` as well as the log line and event | **new (review)** | Run totals are a `SUM`, not an event scan |
| D47 | `require_token` forces operator auth on a loopback bind | **new (review)** | A reverse proxy in front of loopback would otherwise expose the API unauthenticated |
| D48 | `Workflow` lives in `athanore/workflow.py`, composing the pure `graph` builder and the plugin declarations | **new (review)** | Plugin decorators on the graph object would have broken "graph imports nothing" |
| D49 | JSON-Schema-driven forms use `@rjsf/core` + `@rjsf/shadcn`; the client and TanStack Query options are generated by `@hey-api/openapi-ts`; fonts are bundled via fontsource | **new (review)** | A hand-written schema walker and hand-written query keys were wheels; a local tool must not phone Google Fonts |
| D50 | `panel` is a plain call; plugin manifest and panel kinds ship in the API phase so the SPA pane host is built on the manifest from day one | **new (review)** | Decorating an unused function was misleading; building panes twice (hard-coded, then on the manifest) was the plan's largest waste |
| D51 | Delete run is `D` (shift), keeping `d` for deny in the request panel | **new (review)** | Two destructive-adjacent meanings on one key, one focus ring apart |
| D52 | Shutdown interrupts attempts and leaves their rows `in_progress`/`waiting`; recovery resets them; `cancelled` is reserved for operator intent; `engine.stopping` records the interruption | **new (gap review 2026-09-05)** | 04 said shutdown records `cancelled` while recovery only reset `in_progress`, so a graceful stop lost work a crash would have recovered |
| D53 | Event payloads are typed per event name (18) and exposed in OpenAPI as a discriminated union on `name` | **new (gap review)** | The SPA, plugins, and CLI key on payload fields; "typed end to end" was false while `Event.data` was a dict |
| D54 | `settings.agent_command` (env/CLI only) swaps every `ACPAgent.command`; `FakeACPAgent` picks a scenario per `<workflow>.<node>`; examples ship scenarios | **new (gap review)** | "Examples green on the fake" was the phase gate with no mechanism behind it |
| D55 | Node-slot panel liveness rides on `GET /api/runs/{id}/graph` as `live`; the manifest stays static; `workflow`/`global` plugin contexts have no run and only run-independent services | **new (gap review)** | Liveness "computed server-side" had no transport |
| D56 | The agent-facing task read returns the work log without `kind=stats` lines, uncapped, oldest first | **new (gap review)** | Token counts are operator information; the MVP showed them and they distracted small models |
| D57 | `position {index}` is zero-based and clamped; `direction` at the ends is a 200 no-op; New Run "top" = index 0 | **new (gap review)** | The index base was unspecified and the New Run overlay depends on it |
| D58 | `run.output` is one value when the run ends with one terminal task and a list in branch order when several branches terminate independently; `RunDetail.outputs` always lists per-branch values; terminal tasks carry `terminal` | **new (gap review, revised)** | The MVP's "last branch wins" picked the value by a race; shape-by-structure is deterministic, and closing a fan-out with a join (D62) gives the single-value shape |
| D63 | Agents reach their task through three tooling tiers over one HTTP substrate: `mcp` (in-process MCP server passed on `new_session`, default when advertised), `native` (a harness extension, pi's in `examples/pi`), `http` (the curl block, fallback); the token leaves the prompt in the first two | **new (2026-09-05)** | Tools beat prompt-embedded curl for small models and for token hygiene, but pi has no MCP client, so MCP alone would strand the default agent |
| D62 | Fan-in: `@wf.node(join=True)` collects every branch of a fan-out; branch frames on tasks, durable `join_arrivals`, join dispatched in the arriving task's transaction; partial join at quiescence is `failed join_incomplete`; late arrivals recorded; `move` into a join rejected | **new (gap review)** | Without fan-in no node could run after all branches; metadata on the node seam plus one mechanism, not a fourth rule |
| D59 | The MVP findings the docs cite are folded into 20 so `docs/v1` is self-contained | **new (gap review)** | Agents building from the docs in a sandbox cannot read git-ignored files |
| D60 | Three timeouts nest (node, agent, wait); node timeout raises `TimeoutError` in the body, agent timeout raises `AgentError` after recording stats, both retryable; failed `AgentResult` is returned, not raised | **new (gap review)** | Which clock fired and what a body sees was implicit across 04 and 05 |
| D61 | Verbatim prompt blocks (19) are part of the contract and byte-tested; only the `/api/agent/` path and header-only token differ from the MVP | **new (gap review)** | Every example was tuned against that wording; drift would show up as example regressions with no test pointing at the cause |

| D64 | The dev stack (`compose.yaml`, `docker/dev/`, `scripts/`) lives in this repository, not in the separate `athanore-build` repo T000 assumed; one image backs the `dev` shell, the `app` server, the `web` server and both ACP agents, and the `scripts/` wrappers run the same on the host and inside the container | **new (2026-09-05)** | The gate an agent runs has to be the gate a human runs; a second repository holding the toolchain is a second thing to keep in step. T000's driver workflows (v0 dispatching the plan) remain out of scope here |

## Open questions (not blocking)

1. Should `allow_always` answers be surfaced as a per-run allowlist the
   operator can inspect and revoke? Today the agent's own rule is the
   mechanism (carried). Leaning: expose read-only in the task drawer.
2. Default retention windows (14 d transcripts, 30 d events) — revisit
   after real usage.
3. Whether the inbox should support bulk "allow all from this task".
   Leaning yes, as a plugin action on the `requests` builtin.
4. **Closed by D59 (T001).** `docs/design/*` and `docs/bugs/*` are
   git-ignored in the MVP repository. The findings v1 cites are folded
   into 20, so `docs/v1/` is self-contained and nothing depends on that
   history. Un-ignoring it for its own sake is not a v1 question.
5. Run retention. Runs never expire and `GET /api/runs` returns them
   whole; fine for months of local use, but an `archived` flag or a
   default `?limit=` will be wanted before the list stops being "small".

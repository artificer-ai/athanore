# 13 — Testing and quality

The MVP's 200+ tests are the behavioural specification of the engine,
agents, requests, and API. v1 keeps their assertions and re-homes them;
the TUI suite (2,474 lines) is retired with the TUI and replaced by SPA
tests of the same behaviours.

## Pyramid

| Layer | Tooling | What |
|---|---|---|
| Unit | pytest, hypothesis | `graph` (signature parsing, finalization errors, generations — property-tested with random DAGs and cycles), `routing.interpret`, validators, stats builders, formatters |
| Store | pytest-asyncio, SQLite tmp file, Postgres in nightly | Repositories, claim ordering, cascade delete, outbox ordering, migrations up/down, v0 import on the MVP's fixture databases |
| Engine | in-process `Server` on a free port, `MockAgent` / `StatsMockAgent` | Fan-out completion, fan-in (join receives branches in index order; nested fan-out/join; dead-lettered branch → `failed`, retry → join fires → `completed`; branch terminating instead of joining → `join_incomplete`; late arrival recorded, not re-fired; recovery mid-fan-out; `output` shape by terminal count), loop-backs, retries/dead-letter, recovery, pools (dedicated/shared/zero), pause/resume, cancel kills, waiting releases the slot, priorities |
| Agent façade | `FakeACPAgent` subprocess | Session lifecycle, config by category, streaming, permissions by kind, elicitation bridge, HTTP ask, repair turns, truncation via a fake stats provider, env scrubbing, timeout/cancel/refusal exit paths, stats on every path, tooling tier selection (`auto` → `mcp` when advertised, else `http`; the `mcp` tier through `mcp_calls`; the athanore tool server auto-allowed under `ask`) |
| API | httpx against the live app | Every endpoint, auth matrix (loopback plain / network bind with and without token / task token / expired task token), error shapes, 413, SSE replay and live, OpenAPI snapshot |
| Plugins | a test workflow with one of each declaration | Manifest, scoping (404 on foreign run), action validation, node liveness, assets served, `on` handlers |
| SPA unit | Vitest + Testing Library | Renderers per kind, ActionForm round-trips nested schemas and arrays, invalidation table precedence and coalescing, SSE wrapper reconnect and `resync`, keymap scoping |
| E2E | Playwright against `athanore serve` with example workflows on `FakeACPAgent` | Submit → watch graph → answer permission → answer human_input → completion; reorder; pause/resume; server-down banner; keyboard shortcuts; inbox |
| Examples | pytest in `examples/` | Graph shapes, prompts inlined, models declared (from the MVP's `test_gamedev`, `test_agents`) |

## Contract tests

- `openapi.json` is snapshotted; any diff must be reviewed. The SPA's
  generated types are rebuilt from it in CI and the typecheck must pass.
- The event vocabulary (03) is a Python enum and a TypeScript union
  generated from it; a test asserts every emitted name is in the enum.
- Error codes are an enum on both sides.

## Fakes

- `FakeACPAgent`: a Python script speaking ACP over stdio, driven by a
  JSON scenario (below). It is the only "agent" CI runs.
- Scenario vocabulary (`athanore/testing/fake_acp.py`, `--scenario
  <path>` or `ATHANORE_FAKE_SCENARIO`): `text: [str]` (assistant chunks,
  one `agent_message_chunk` each), `thoughts: [str]`, `tool_calls: int |
  [{title, kind, raw_input?}]` (each emits a `tool_call` start and a
  `tool_call_update` completion), `permissions: [{options: [{kind,
  option_id?, name?}], title?}]` (sent in order, in the listed option
  order; `"reject_first"` is a shorthand for the claude-agent-acp order),
  `elicitations: [{schema, mode: "form" | "url"}]`, `config_options:
  [{id, category, values}]` (advertised on `session/new`; defaults to pi's
  `model` and `thought_level`), `reject_config: [id]` (ids whose `set`
  fails), `usage: {input, output, thought?, cache_read?}` (the UNSTABLE
  `PromptResponse.usage`), `stop_reason: "end_turn" | "refusal" |
  "cancelled"`, `sleep_s: float` (before answering the prompt; drives
  timeouts), `session_file: {dir, cost?, stop_reason?, model?}` (writes a
  pi-layout JSONL so `examples/pi/stats.py` is testable), `log: str`
  (POSTs it to `$ATHANORE_TASK_URL/log` with `$ATHANORE_TASK_TOKEN`),
  `submit: json | [json]` (POSTs each; the last valid one wins, so a
  first invalid element exercises the 422 + repair path), `repair_submit:
  json` (what to submit when a repair turn arrives), `request_log` /
  `response_log: path` (JSON lines of received requests / responses the
  fake initiated), `env_echo: bool` (emits an `agent_message_chunk`
  listing the environment under an `[env]` marker, for scrub tests — ACP
  has no wire form for a `notice`, which is a kind the façade itself
  writes, 05), `advertise_mcp: bool` (report `mcpCapabilities.http` on
  `initialize` and record the `mcpServers` received on `session/new`),
  `mcp_calls: [{tool, args}]` (connect to the received MCP server with
  the `mcp` client and call each tool in order, emitting the results as
  tool-call updates carrying content — the transcript's `tool_result`;
  exercises the `mcp` tier end to end). Unknown keys are an error.
- A scenario scripts **one run**: every content block above is emitted on
  the first prompt turn, and the repair turns that follow it submit
  `repair_submit` and nothing else. `sleep_s`, `stop_reason` and `usage`
  belong to a turn and apply to every one (D122).

### Running examples on the fake

`ATHANORE_AGENT_COMMAND` (02, 05) replaces every `ACPAgent.command` with
the fake. Scenario selection is per node: the fake reads
`ATHANORE_FAKE_SCENARIOS=<dir>` and picks `<workflow>.<node>.json`, then
`<node>.json`, then `default.json`, using the `workflow` and `node` the
kickoff prompt names (the fake parses its own prompt, which is why 19 is
byte-exact). `examples/<wf>/scenarios/` ships one per node, each of which
`log`s a plausible deliverable and `submit`s a value that satisfies the
node's `output_model`, so every example runs to `completed` with no model
in the loop. That is the phase gate of 14 and the Playwright fixture of
10.
- `FakeStatsProvider`: returns scripted session stats / stop reasons.
- Time: `freezegun` for retention; the scheduler tick is injectable.

## Live smoke (manual, documented)

`tests/smoke/` keeps opt-in scripts against real pi and Claude ACP
adapters (`ATHANORE_SMOKE=1`), never run in CI.

## CI

GitHub Actions: `uv sync`, ruff, pyright, import-linter, pytest (SQLite),
pnpm typecheck/lint/vitest, build SPA, Playwright, OpenAPI snapshot check,
`pip-audit`, `pnpm audit`. Nightly: Postgres matrix. Coverage gates:
`graph`/`engine`/`requests` ≥ 95 %, overall ≥ 85 %; `web/src` ≥ 80 % on
statements, branches, functions and lines, configured in
`web/vite.config.ts` so that `pnpm -C web test` — which is what both the
gate and CI run — applies it (D177).

## Definition of done for a feature

Tests at the lowest layer that can express the behaviour, an API or
event change reflected in the snapshot, a decision recorded in 15 if a
choice was made, and the relevant document here updated.

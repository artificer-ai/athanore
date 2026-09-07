# 05 — Agents and the ACP façade

Bodies await agents; the engine never sees them. Everything the MVP's
`agents.py` and `stats.py` do is kept; the module is split by concern and
the vendor-specific parts move out of the package.

## Agent classes

```python
class Agent:                       # base façade
    system_prompt: str | None = None
    output_model: type[BaseModel] | None = None
    ask_policy: Literal["off", "http"] = "off"
    async def run(self, prompt: str = "") -> AgentResult: ...

class ACPAgent(Agent):
    command: list[str] = ["npx", "pi-acp"]
    model: str | None = None
    thinking: str | None = None
    permission_policy: Literal["ask", "auto_allow", "auto_deny"] = "ask"
    permission_timeout: float | None = None
    permission_timeout_action: Literal["deny", "allow"] = "deny"
    elicitation_policy: Literal["ask", "decline"] = "ask"
    max_repair_turns: int = 2
    env_allowlist: list[str] | None = None   # None: inherit (scrubbed); list: allow-nothing-by-default (12)
    tooling: Literal["auto", "mcp", "native", "http"] = "auto"   # how the agent reaches its task (§Tooling tiers)
    client_class = ACPClient
    stats_provider: SessionStatsProvider | None = None
    def __init__(self, command=None, cwd=None, timeout=None, env=None): ...
```

Decisions carried from the MVP: an agent is a class carrying its config;
shared config is a base class; the prompt is inlined text; `model` and
`thinking` are sent as ACP config options resolved **by category** from
what the session advertises (20 §Finding 2: categories `model` and
`thought_level`, ids differ per agent);
rejected config options are logged, never swallowed. The findings behind
these rules are folded into 20.

`settings.agent_command` (env `ATHANORE_AGENT_COMMAND`, a JSON list or a
shell-split string) overrides `command` on **every** `ACPAgent` at spawn
time regardless of subclass. It exists for one purpose: running the
example workflows on `FakeACPAgent` in CI and the phase gates (13
§Running examples on the fake). It is logged at startup when set and
never read from `athanore.toml`, so a production config cannot swap
agents by accident.

`template=` (prompt from a file) is dropped. It was superseded by inlined
prompts and only survives in tests.

### AgentResult

```python
@dataclass
class AgentResult:
    status: Literal["complete", "failed"]
    output: Any            # validated output_model instance, or raw submission
    text: str              # concatenated assistant text
    session_id: str | None
    stop_reason: str | None
    error: str | None
    stats: dict            # the stats entry that was recorded
    ok: bool               # property
```

A `failed` result is returned (not raised) for refusal/cancel/truncation
so bodies can decide; `AgentError` is raised for timeouts, transport
failures, missing or invalid submissions. Both paths record stats.

## Tooling tiers: how an agent reaches its task

An agent needs four capabilities: read its task, append to the work log,
submit a result, ask the operator. The MVP delivered them as curl lines
in the prompt with the task token inline. v1 delivers the same four
capabilities through whichever of three adapters the agent can use
(D63); all three sit on the agent HTTP API of 08, which stays the single
substrate (token scoping, endpoint validation, the 422 repair path, the
long-poll).

| Tier | When | Mechanism |
|---|---|---|
| `mcp` | the agent's `initialize` response advertises `mcpCapabilities.http` | `new_session(mcp_servers=[McpServerHttp(name="athanore", url=f"{public_url}/mcp/agent", headers=[X-Athanore-Token])])`. The server is in-process (08 §MCP) and exposes `get_task`, `append_log`, `submit_result`, `ask_operator`, `wait_answer`. `submit_result`'s input schema **is** the node's `output_model` schema, so the model sees it as a tool definition; a validation failure returns as the tool result and the model fixes it inside the same turn |
| `native` | the agent harness has its own tool registry and an athanore adapter is installed (pi: `examples/pi/extensions/athanore.ts`, registered with `pi.registerTool()`) | The extension reads `ATHANORE_TASK_URL` / `ATHANORE_TASK_TOKEN` from the environment the façade exports and calls the HTTP API. Cannot be auto-detected; the agent class sets `tooling="native"` |
| `http` | everything else, `FakeACPAgent`, agents that cannot reach the server over HTTP MCP | The curl block of 19, token in the header line |

`auto` picks `mcp` when advertised, else `http`. The kickoff text (19) has
a tool-agnostic core naming the four capabilities and one tier-specific
block. In `mcp` and `native` tiers the token never appears in the prompt
and therefore never reaches the model provider (12 §Task tokens).

Verified 2026-09-05: pi-acp 0.0.33 advertises `mcpCapabilities: {http:
false, sse: false}` and pi 0.84 has no MCP client, so pi agents use the
`native` tier (the example extension) or `http`; `@agentclientprotocol/
claude-agent-acp` is expected to take the `mcp` tier (Claude Code has a
native MCP client; confirm at A6.1). Under the `ask` permission policy a
permission request whose tool call names the `athanore` MCP server is
answered `allow_once` without asking (it is the agent talking to its own
task; the transcript still records the tool call), so a log append never
becomes a prompt.

## Prompt assembly

```
system_prompt
---
## Your assignment
<prompt argument>
---
## Your task                       omitted outside a task context
Work on task N "title" — stage "node" of workflow "wf" (run R).
[tier block, mcp/native]           the tool list: get_task, append_log, submit_result, …
[tier block, http]                 curl GET  {api_base}/api/agent/tasks/N     (read title, description, FULL work log)
                                   curl POST {api_base}/api/agent/tasks/N/log (append your deliverable before finishing)
[## Asking the operator]           http tier only, when ask_policy == "http"
[## Submitting your result]        http tier only, when output_model is set: exact curl + JSON schema
```

The exact wording of every block, including the repair-turn text, is
fixed in 19 and asserted by tests; the MVP's text is carried verbatim
with only the path and header changes below. A section with nothing to
say is omitted **with its separator**, so an agent carrying no
`system_prompt` opens on its assignment rather than on a `---` (19
§Assembly). In the `mcp` and `native` tiers the ask block is dropped —
the tool's own description carries it — and the submission block becomes
the one line pointing at `submit_result`'s input schema.

The task token is passed in the `X-Athanore-Token` header of the injected
curl lines, and is also exported to the subprocess as `ATHANORE_TASK_TOKEN`
/ `ATHANORE_TASK_URL` so an adapter that can read env can keep it out of
the prompt (12). All agent-facing routes live under `/api/agent/` (08).
v1 no longer accepts the token as a query parameter or a body field (12). Prompts, and therefore tokens, do reach the model provider;
tokens are single-task, revoked when the task finishes, and useless
outside `/api/tasks/{id}/…`.

## The ACP client

`ACPClient` (module-level, injectable) implements the ACP `Client`
callbacks:

- `session_update`: assistant text, thought chunks, and tool-call
  starts/updates go to the transcript (`StreamChunk`, kinds `text` /
  `thought` / `tool_call` / `tool_result`; façade notices are `notice`)
  via `ctx.services.stream`; a flusher persists in batches every
  `stream_flush_interval` and publishes `task.stream`.
- `request_permission` → `agent.resolve_permission()` (policies below).
- `create_elicitation` → `agent.resolve_elicitation()`.
- `fs/*` and `terminal/*` return `method_not_found` (verified harmless;
  agents do their own I/O). Later seam: implement them for agents that
  want the client to own the filesystem.

### Session lifecycle in `ACPAgent.run()`

1. Spawn `command` with `cwd`, scrubbed env (`CLAUDE_*`, `CLAUDECODE`,
   `CLAUDE_PID` removed, or only `env_allowlist` kept; then
   `ATHANORE_TASK_TOKEN` / `ATHANORE_TASK_URL` and the explicit `env`
   merged), stdin/stdout piped, stderr captured to the structured log.
   Two bounds on that pipe pair, both of them the difference between a
   diagnosis and a hang:
   - **stderr is capped at 64 KiB** (`STDERR_CAP`). The first 64 KiB is
     logged line by line at DEBUG; past the cap the pump keeps *reading*
     and stops logging. A crashing adapter can produce megabytes and the
     structured log is not the place for them (12 §Agents), but
     abandoning the pipe is worse than logging it: a full pipe blocks the
     child on its next write, and a child blocked on stderr looks exactly
     like a slow model.
   - **stdout is buffered at 8 MiB** (`STDOUT_LIMIT`). One ACP frame is
     one line, and a tool call's `rawInput` — a file the agent just read
     — routinely exceeds asyncio's 64 KiB default, which fails the read
     rather than the tool call (D124).
2. `initialize` (client info carries the real `athanore.__version__`),
   `new_session(cwd)`, set `model` / `thinking` by category.
3. Declare `output_model` and `ask_policy` on the `TaskContext` for the
   duration (restored afterwards, so a body can run agents in sequence).
4. `prompt(full_prompt)` under `timeout`.
5. Repair loop: while the turn ended `end_turn`, an `output_model` is
   declared, and no valid submission is stored, send up to
   `max_repair_turns` follow-ups on the **same session** quoting the last
   422 (`submission.repair` event, notice in the transcript).
6. Outcome: `refusal`/`cancelled` → failed result; final-turn truncation
   (below) → failed result; else attach the latest submission (validated
   against `output_model`; missing → `AgentError`).
7. `finally`: flush the transcript, close the connection, stop the
   subprocess, record the stats entry exactly once (work-log line,
   `agent.stats` event, and `tasks.stats` column, 07). Each step is
   guarded on its own — a connection that will not close must not leave
   a child running, and neither may stop the stats entry being written —
   and the transcript is flushed, not closed: it belongs to the attempt,
   so a body running two agents in sequence still has somewhere to write
   (D124).

   Stopping the child is three steps and **a five-second grace period**
   (`KILL_AFTER`): close its stdin, which is how a well-behaved adapter
   is asked to exit on its own; `terminate()`; and `kill()` if it has not
   exited within `KILL_AFTER`. The child is always waited on, so
   `returncode` is set by the time `run()` returns and a long-lived
   server collects no zombies — on the timeout and cancellation paths as
   much as on the clean one. Five seconds is a shutdown budget, not a
   turn's: the agent has already been told to stop, and an adapter that
   is still writing after it is one this process cannot wait for.

### Truncation detection is a provider concern

The MVP reads pi's session JSONL from `~/.pi/agent/sessions` to detect a
final turn cut off at the max output tokens, and to read token usage and
cost. That knowledge is pi-specific. v1 introduces:

```python
class SessionStatsProvider(Protocol):
    async def stats(self, session_id: str, cwd: str | None) -> SessionStats | None
    async def final_stop_reason(self, session_id: str, cwd: str | None) -> str | None
```

`ACPAgent.stats_provider` defaults to `None`: tokens come from the ACP
prompt response `usage` field when the agent sends it (`PromptResponse.usage`
in SDK 0.12.1: input/output/total plus thought and cache counters; still
marked UNSTABLE), otherwise they are omitted. `examples/pi/stats.py` ships the
pi session-file provider (the MVP's parser, tests included) and the pi
example agents set it. Truncation detection uses the same provider.

## Policies

### Permissions (`permission_policy`)

| Policy | Behaviour |
|---|---|
| `ask` (default) | Open an `options` request (06) with the agent's options verbatim and a bounded tool-call summary; block the agent until answered; on `permission_timeout` apply `permission_timeout_action` with an `engine`-authored answer |
| `auto_allow` | Choose by kind: `allow_once` then `allow_always`; raise `AgentError` if neither is offered |
| `auto_deny` | Choose `reject_once` then `reject_always`; raise if neither |

Outside a task context `ask` degrades to `auto_allow` with a warning.
`settings.permission_policy` may force a global default (CI). Selecting
by kind, never by index, is a hard rule (20 §Finding 1). The MVP's caveat
stands: ACP permission requests are advisory; hard denies belong in the
agent's own settings (e.g. `.claude/settings.local.json` deny rules; 20
§Caveat). The stats entry counts `denied_permissions` so a run whose
agent was refused everything is visible.

### Elicitation (`elicitation_policy`)

`ask`: bridge form-mode elicitations to a `form` request with the agent's
`requestedSchema`, validate the answer against it (light JSON-schema
validator), return `accept` + content. URL mode is declined.
`elicitation/complete` is accepted and ignored. `decline`: always decline.

### HTTP ask (`ask_policy="http"`)

Opt-in per class. Adds the how-to to the prompt; the agent may
`POST /api/agent/tasks/{id}/ask` and long-poll
`GET /api/agent/tasks/{id}/requests/{rid}?wait=60`. Off by default so an
unattended pipeline cannot be stalled by a chatty model.

## Submissions

- The endpoint validates against the declared `output_model` and rejects
  misfits with 422 + errors + schema; only valid payloads are stored;
  last valid wins; history kept.
- Without an `output_model`, submissions are stored raw.
- `_token` in the body is no longer accepted (12).
- Submissions deliver values, never transitions (invariant 1 in 03).

## Stats entry

Recorded once per `run()` on every exit path, as a `[stats]` work-log line
(author `engine`) and an `agent.stats` event:

`node`, `attempt`, `status` (`ok` / `failed` + reason), `model`
(provider-reported, else the class's `model`), `input_tokens`,
`output_tokens`, `total_tokens` (input + output; ACP usage wins over the
provider when present), `tool_calls` (ACP `ToolCallStart` count), `cost`
(provider only), `duration_s` (whole seconds, the resolution the work-log
line quotes), `session_id`, `repair_turns` (when > 0),
`denied_permissions` (count of `reject_*` answers, when > 0), `reason`
(with `status=failed`: `refusal`, `cancelled`, `truncated`, `timeout`,
`shutdown`, `transport`, `no_submission`). Fields that cannot be
determined are omitted. Never raises. The text form is
`format_stats_line` from the MVP, unchanged:
`[stats] node=qa attempt=2 ok — model=…, tokens=12,406 in / 1,204 out /
13,610 total, tools=23 calls, repairs=1, cost=$0.0000, 142s, session=01a01646`.

## Testing doubles (`athanore.testing`)

- `MockAgent(output=… | submit=… | log=… | stream=… | fail=…)` — no
  subprocess; `submit=` exercises the real endpoint with the real token,
  and `fail=` raises the `AgentError` a body has to route around.
  `output=`, `submit=` and `log=` each take either a value or a
  zero-argument callable, so a body that runs the same agent on several
  attempts scripts them by closing over a counter; `stream=` and `fail=`
  take a value.
- `StatsMockAgent(stats=…, fail=…)` — records a stats entry like the
  façade; `stats=` takes a value or a zero-argument callable, and `fail=`
  is `True` for a transport failure or one of §Stats entry's reasons.
- `FakeACPAgent` — a real subprocess speaking ACP over stdio, scriptable
  (text chunks, tool calls, permission requests, elicitations, usage), so
  the façade is tested end to end without pi or Claude.

## User-land adapters (examples, not shipped)

`examples/` keeps: pi (default command, stats provider), Claude Code via
`@agentclientprotocol/claude-agent-acp` (command + model only), the Docker
sandbox (`docker run -i … athanore/pi-acp` as the ACP command;
`permission_policy="auto_allow"` because the container is the guardrail),
and the `projects` triage workflow. `examples/` has its own `pyproject`
extras and tests; the core package imports none of it.

Pinning: examples pin agent adapter versions (`npx -y pkg@x.y.z`) instead
of floating `npx -y pkg` (12 §Supply chain).

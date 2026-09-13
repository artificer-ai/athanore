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
    tooling: Literal["auto", "mcp", "native", "http", "none"] = "auto"   # how the agent reaches its task, or "none" (§Tooling tiers)
    client_class = ACPClient
    stats_provider: SessionStatsProvider | None = None
    def __init__(self, command=None, cwd=None, timeout=None, env=None,
                 session_id: str | None = None): ...
    def open(self) -> AbstractAsyncContextManager[AgentSession]: ...

class AgentSession:                # what open() yields
    session_id: str                # once open
    async def prompt(self, prompt: str = "") -> AgentResult: ...
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

`session_id=` continues a session an earlier run opened (23 §Surface,
D254). It is an argument of construction, beside `cwd`, `timeout` and
`env`, because it is per-instance configuration of the same kind —
*where* and *how* this run happens — and `AgentResult.session_id` is
where it comes from:

```python
first = await Reviewer(cwd=checkout).run(assignment)
again = await Reviewer(cwd=checkout, session_id=first.session_id).run(follow_up)
assert again.session_id == first.session_id
```

The `cwd` MUST be the one the session was opened with; the agent
enforces it, and the façade reports the refusal. A run constructed with
`session_id=` either continues that session or raises `AgentError` —
never a `session/new` in its place — per §Continuing a session below.

`open()` holds one session open for a block (23 §A session held open,
D264). `run()` pays for a process per prompt — spawn, `initialize`,
open the session, one prompt, stop — which is the cost of doing
business for a pipeline stage and a cold process on every message for
a body that talks to the same agent turn after turn. `open()` is
`run()` split in two: the body says when the conversation starts and
when it ends, and prompts in between.

```python
async with ChatAgent(cwd=checkout).open() as agent:
    while True:
        said = await human_input(ask)                # parks; slot given back
        if said in STOP_WORDS:
            return said
        reply = await agent.prompt(said)             # same process, same session
```

- `open()` is an async context manager and nothing else: there is no
  `close()` to forget, and the exit of the block is the end of the
  session on every path — return, exception, cancellation.
- `run(prompt)` **is** `async with self.open() as s: return await
  s.prompt(prompt)`. One code path; the one-shot form is the held form
  with one prompt, and §Session lifecycle is unchanged for it.
- `prompt()` takes the assignment text and returns an `AgentResult`,
  exactly as `run()` does. The assembly of 19 applies to every prompt:
  `system_prompt` is sent by the adapter per session, and the
  assignment, task block and tier block are the prompt's. A body that
  wants a shorter second prompt writes a shorter assignment; the façade
  does not edit what it is given.
- On an agent constructed with `session_id=`, `open()` continues that
  session (§Continuing a session) and holds it.
- `AgentSession.session_id` is the id the agent gave, or the one
  continued, available from the moment the block is entered. It is the
  one thing a body should write down — to the work log, or into what it
  returns — because it is what a re-executed attempt hands back as
  `session_id=` (§Holding a session, step 6).

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

What one `run()`, or one `prompt()` on a held session, produced. A
`failed` result is returned (not raised) for refusal/cancel/truncation
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
| `none` | the body wants only what the agent *says* — a chat, a summariser, a classifier — and the agent has no business with its task; the class sets `tooling="none"` (D271) | Nothing. The whole `## Your task` section of 19 is omitted, as it is outside a task context; no MCP server goes on the session; `ATHANORE_TASK_URL` / `ATHANORE_TASK_TOKEN` are not exported to the child. The attempt's token still exists — it is the attempt's, and `TaskContext` carries it — it is simply never handed to a process with no use for it |

`auto` picks `mcp` when advertised, else `http`; `none` is never picked,
only declared. The kickoff text (19) has a tool-agnostic core naming
the four capabilities and one tier-specific block. In `mcp` and
`native` tiers the token never appears in the prompt and therefore
never reaches the model provider (12 §Task tokens); in `none` it
reaches neither the prompt nor the process. An agent on `none` cannot
submit, so an `output_model` on such a class is a configuration error
and `AgentError` says so before any prompt: a body that declares both
has asked for a value from an agent it gave no way to deliver one.
`AgentResult.text` is what a `none` agent returns, and the repair loop
never runs for it.

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
  `stream_flush_interval` and publishes `task.stream`. While the client
  is `replaying` — the façade sets it around a `session/load` and
  nowhere else — an update writes no chunk, adds no text and counts no
  tool call; every update received under the flag is counted, whatever
  its kind, and the count is logged once at DEBUG (`replay discarded`,
  `count=`) when the flag clears. `request_permission` and
  `create_elicitation` do not read the flag and are answered as ever
  (§Continuing a session).
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
   then `new_session(cwd, mcp_servers)` — or, on an agent constructed
   with `session_id=`, the re-open of §Continuing a session — and set
   `model` / `thinking` by category from the response's `configOptions`,
   whichever method answered.
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

### Continuing a session

The lifecycle above with step 2 replaced, for a run on an `ACPAgent`
constructed with `session_id=`. 23 §Lifecycle of a continued run is
where the reasoning lives; this is the fold.

1. Spawn is unchanged: the same command, the same scrubbed environment,
   and the task's `ATHANORE_TASK_URL` / `ATHANORE_TASK_TOKEN` — **this**
   task's, not the one the session was opened under. Tokens are per
   task (12 §Task tokens); a continued session is not a continued token.
2. After `initialize`, the façade chooses from what the agent
   advertised, in this order: `session/resume` when
   `agentCapabilities.sessionCapabilities.resume` is present; else
   `session/load` when `agentCapabilities.loadSession` is true; else it
   raises `AgentError` — `<Agent> cannot continue a session: the agent
   advertises neither session/resume nor session/load` — before any
   prompt, with the child stopped. Both calls take `session_id`, `cwd`
   (`self.cwd or os.getcwd()`) and the same `mcp_servers` a
   `session/new` would carry for this run's tier (§Tooling tiers), so
   the `mcp` tier's server carries this task's token, and `mcpServers`
   is `[]` outside it on both methods as it is on `new`. `resume` comes
   first because it is the cheaper of the two on the wire and produces
   nothing to discard; `load` is the one every adapter that persists
   sessions has (D255). The response's `configOptions` is configured
   exactly as a `session/new` response is — `model` and `thinking`
   resolved by category and set, a rejected option logged and written
   as a `notice`, never swallowed — because the class is the
   configuration and a session that drifted from it is not the one the
   workflow author declared. `session.session_id` is set to the
   requested id only when the call **succeeds**: a run that failed to
   join a session did not have one, and its stats entry MUST NOT name
   it.
3. Between sending `session/load` and receiving its answer the client is
   **replaying**: `session_update` writes no chunk, appends no text and
   counts no `ToolCallStart`; a `request_permission` or
   `create_elicitation` is answered as it would be outside a replay,
   because a request dropped on the floor would hang the adapter. The
   flag is set immediately before the one `load_session` call and
   cleared on every path out of it — an error, a dropped connection, a
   cancellation, a timeout — and `session/resume` never sets it. The
   number of updates dropped is logged once at DEBUG (`replay
   discarded`, `count=`) so a transcript that looks too short has a line
   saying why. The replay is discarded rather than recorded because the
   replayed turns already have a transcript, on the attempt that ran
   them: a `StreamChunk` belongs to the task that produced it (03
   §StreamChunk), and a replay produced nothing.
4. Once the session is open, and before configuration, the façade writes
   one `notice` chunk, `continuing session <session_id>`, through the
   client's `append`. It is the first chunk of the continued attempt's
   transcript on both paths — before any configuration notice, and
   whichever method the agent had (D258, D265) — and the one line that
   tells a reader why this transcript starts in the middle of a
   conversation.
5. Prompt, repair and outcome are unchanged (steps 4–6 above); the repair
   loop runs on the continued session. Cleanup and accounting are
   unchanged in mechanism (step 7); what the entry carries on a continued
   run is §Stats entry.

**Refusal.** A continued run raises `AgentError` and returns nothing
when the agent advertises neither method (the message in step 2, after
`initialize` and before any prompt, the child stopped); when the agent
answers `session/load` or `session/resume` with a JSON-RPC error — an
unknown id, a `cwd` that is not the session's, a session it can no
longer read — with the message `the agent could not continue session
<id>: <the agent's message>`; and for anything a fresh run would already
raise for, which includes a connection dropped during the re-open (the
`transport` failure a fresh run reports for the same thing at
`session/new`). All of them record one stats entry with `status=failed`
and `reason=transport`, no new reason, and no `session_id`, because none
was joined. There is deliberately **no fallback** to `session/new`: a
body that asked for a session it cannot have is misconfigured, and a run
that quietly started over would answer with no memory of the
conversation and report success — the precedent is §Policies, where
`auto_allow` raises rather than picking another option (D254).

### Holding a session

`open()` is the seven steps above split at the block's edges: steps 1–3
at entry, steps 4–6 per `prompt()`, step 7 at exit. 23 §A session held
open is where the reasoning lives; this is the fold.

1. **Entry**: spawn (step 1), `initialize`, `session/new` — or
   `session/resume` / `session/load` when constructed with
   `session_id=` (§Continuing a session, step 2) — and the config
   options set by category (step 2). `output_model` and `ask_policy`
   are declared on the `TaskContext` for the length of the block (step
   3): the class is the configuration, and one class holds one session.
   The whole of entry, spawn included, runs under `timeout` (step 4),
   because a handshake that never answers must not hang the body; on
   any failure the child is stopped, one stats entry is recorded
   `failed/transport` (or `timeout`, or `shutdown` on a cancellation),
   naming the session only if one was actually joined, and `AgentError`
   leaves `open()` — the block is never entered.
2. **Each `prompt()`**: the render, the prompt under `timeout`, the
   repair loop, the outcome (steps 4–6), all as `run()` does them; the
   repair turns are on the held session, as they are on any. `timeout`
   bounds *one prompt and its repairs*, as it bounds one run; nothing in
   the façade bounds the block, and nothing should — a chat idles for
   hours by design. The node's own `timeout` is the bound on the whole
   session, and 04 §Timeouts already pauses it while the task is
   `waiting`, which is exactly the time a chat spends parked on a
   person.
3. **After each `prompt()`**: the transcript is flushed and **one stats
   entry is recorded** for that prompt (§Stats entry). The result
   returned is the prompt's, and it carries `session_id`. Submissions
   stay the attempt's (§Submissions): a second prompt on a class with an
   `output_model` attaches the attempt's latest valid submission, as two
   `run()`s in one body do.
4. **A prompt that fails ends the session's usefulness, not the
   block.** `AgentError` (a transport failure, a timeout, a missing
   submission) and the failed `AgentResult`s (refusal, cancellation,
   truncation) are raised or returned from `prompt()` exactly as from
   `run()`. After a **transport failure or a timeout** the child is
   stopped at once — inside the block — and every later `prompt()`
   raises `AgentError`, `the session is closed: <the reason>`, until
   the block exits; a refusal, a cancelled stop reason, a truncated
   turn or a missing submission leaves the session open, because the
   process is fine and the body may have something to say about it. A
   body that wants to carry on after a dead session opens a new block;
   it does not get a new process behind its back.
5. **Exit**: flush the transcript, close the connection, stop the
   child under `KILL_AFTER` (step 7). **No stats entry** is recorded
   at exit: every prompt already recorded its own, and an exit after
   zero prompts recorded none, because nothing was asked. The steps are
   guarded on their own, as step 7 says, and run on every path — the
   `finally` of the block, so a body's exception, a node timeout and a
   cancellation all reach them; each resource is dealt with once, so
   the stop a dead session did at once and the exit compose. A prompt
   in flight when the body is cancelled records its entry
   `failed/shutdown`, as any cancelled run does (04 §Shutdown), the
   session is closed by it — the agent was mid-turn and its state is
   unknown — and then the exit runs and stops the child.
6. **After a crash**, the attempt re-executes from its first line
   (D6): the block is entered again, and the `human_input`s already
   answered replay their answers by ordinal (06 §Restart durability),
   so the body reaches the first unanswered question at once. The
   session is a fresh one unless the body constructs the agent with
   the `session_id` it wrote down (§Agent classes) — which is the
   composition 23 exists for, and the reason `session_id` is written to
   the work log by any body that holds a session for long.
7. **One prompt at a time.** A second `prompt()` while one is in
   flight is a programming error and raises `RuntimeError` before
   touching the wire; it records nothing, because nothing was sent and
   nothing was spent, and neither does a prompt refused on a dead
   session. A session is not shared between tasks: it is opened inside
   one attempt and dies with it, and the `TaskContext` it declared on
   is that attempt's.

While a held session is parked on a `human_input`, the body holds no
slot (04 §Waiting) and the agent process is alive and idle. The pool
therefore caps agents *answering*, not agents *alive* — a `talk` pool
of 2 is two replies being generated at once, over any number of open
chats (D264). An idle adapter costs memory and a container, and a
conversation that had to give its process up on every question would
be a cold process and a re-pasted history on every message. An
operator who wants to cap live processes caps runs, which is what
`position` and the run list are for.

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

Recorded once per `run()` — once per `prompt()` on a held session
(§Holding a session) — on every exit path, as a `[stats]` work-log line
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

On a continued run (§Continuing a session) the provider's `stats()` is
not consulted: a `SessionStatsProvider` reports a *session*, and a
continued run is a fraction of one whose size the provider cannot know,
so attributing the whole session's tokens and cost to the tenth turn
would be the estimate 01 §Design principles forbids. `input_tokens`,
`output_tokens`, `total_tokens` and `cost` are therefore ACP's per-turn
`usage` or omitted; `model` is the class's, as on any run without a
provider; `final_stop_reason()` is still consulted, because this run's
final turn is the session's final turn and truncation is decided the
same way on both paths; and `session_id` is the continued session's, so
every run on one session carries one id and no `resumed` field is added
(23 §Stats, D256).

On a held session (§Holding a session) there is one entry per
`prompt()`, with `session_id` the held session's on every one — so the
entries of one conversation carry one id, as the entries of a
continued session do. Per entry: `duration_s` is the prompt's, from its
send to its outcome (on every entry, `run()`'s included, so a one-shot
run's entry does not count its spawn and handshake); `input_tokens`,
`output_tokens`, `total_tokens` and `cost` are ACP's per-turn `usage`,
summed over the prompt and its repair turns, or omitted; `tool_calls`,
`repair_turns` and `denied_permissions` are the prompt's; `status` and
`reason` are the prompt's outcome. **The provider's `stats()` is not
consulted on a held session's prompts**, by the same rule as a
continued run: a `SessionStatsProvider` reports a *session*, and an
entry that describes less than the whole session may not carry the
whole session's numbers (D256). A one-shot `run()` is the whole session,
and is the only entry that consults the provider. `final_stop_reason()`
is consulted on every prompt, because every prompt has a final turn.
**No entry is recorded at exit.** The one-line form is unchanged:
`[stats] node=talk attempt=1 ok — …, session=01a01646`, one line per
reply, which is what a reader of a chat's work log expects to see
under each answer.

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
  (text chunks, tool calls, permission requests, elicitations, usage, and
  `prompts` for a session held across several of them, 13 §Fakes), so
  the façade is tested end to end without pi or Claude.

## User-land adapters (examples, not shipped)

`examples/` keeps: pi (default command, stats provider), Claude Code via
`@agentclientprotocol/claude-agent-acp` (command + model only), the Docker
sandbox (`./scripts/agent.sh pi` as the ACP command — the dev stack's own
image and its own way in, rather than a second one built here (D64, D67);
`permission_policy="auto_allow"` because the container is the guardrail,
and the `http` tier because the `native` tier's two environment variables
do not cross `docker compose run`), and the `projects` triage workflow.
`examples/` has its own `pyproject` extras and tests; the core package
imports none of it.

Pinning: examples pin agent adapter versions (`npx -y pkg@x.y.z`) instead
of floating `npx -y pkg` (12 §Supply chain).

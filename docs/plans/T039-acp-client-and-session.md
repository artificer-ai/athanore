# T039 — `ACPClient` and the session lifecycle up to the prompt

**Task.** `docs/v1/17-serial-task-plan.md` § `### T039`.
**Specs.** `docs/v1/05-agents.md` §ACP client and §Agent classes;
`docs/v1/20-carried-findings.md` (ACP behaviours the design depends on);
`docs/v1/12-security.md` §Agent environment.

## What this task is

The real ACP transport: spawn the agent, handshake, configure the
session, send the prompt. The turn loop and cleanup are T039a.

## What this task is not

- No repair loop, no outcome mapping, no stats — T039a. `run()` returns
  the raw `PromptResponse` at the end of this task.
- No vendor knowledge. `command` is configuration; pi and Claude are
  `examples/`.
- `fs/*` and `terminal/*` raise `method_not_found` — the agent works in
  its own sandbox, not through us.

## Steps

1. `class ACPClient(Client)` forwarding `session_update` chunks to
   `ctx.services.stream.append(kind, text)` with 05's mapping:
   `agent_message_chunk → text`, `agent_thought_chunk → thought`,
   `tool_call → tool_call` (counted for stats),
   `tool_call_update → tool_result`. `request_permission` and
   `create_elicitation` delegate to T038; `complete_elicitation` is a
   no-op.
2. `class ACPAgent(Agent)` with 05's attributes.
3. `_child_env()`: scrub `CLAUDE_*`, `CLAUDECODE`, `CLAUDE_PID` — or
   keep only `env_allowlist` when set — then set `ATHANORE_TASK_TOKEN`
   and `ATHANORE_TASK_URL`, then merge explicit `env`. A session-scoped
   variable leaking into a child is how one agent inherits another's
   credentials.
4. `_command()` honouring `settings.agent_command` (the override the
   whole example suite runs on).
5. `run()` up to the prompt: `async with declare(ctx)`; spawn with
   `asyncio.create_subprocess_exec(..., stdin=PIPE, stdout=PIPE,
   stderr=PIPE)`; pump stderr to structlog DEBUG **capped at 64 KiB**;
   `initialize` with client info `athanore/__version__`;
   `new_session(cwd)`; set config **by category**
   (`_resolve_config_id(session, "model"|"thought_level")`), logging a
   rejection at WARNING and writing it as a `notice` chunk; then
   `prompt(render_prompt(...))` under
   `asyncio.timeout(self.timeout or settings.agent_timeout)`.

## Careful

A rejected config id must be **visible**. v0 logs and silently continues
on the agent's default model — which is how a whole build can run on the
wrong model without anyone noticing. The `notice` chunk is what makes it
visible in the transcript; do not drop it.

## Verification

`tests/agents/test_acp_lifecycle.py`, on `FakeACPAgent`:

- the full handshake;
- config ids resolved by category from the advertised list (assert
  against the fake's request log), and a rejected id producing a
  `notice` chunk;
- text and thought chunks landing with the right kinds;
- tool calls counted;
- the env scrub and the allowlist (the fake echoes its env);
- `agent_command` overriding a subclass's `command`;
- a permission with reject-first ordering picking `allow_once`.

## Done

- Tests pass on the fake; no real vendor agent is required by CI.
- `**Status.** Done.` on `### T039`, in the same commit.

## Files

```
athanore/agents/acp.py
tests/agents/test_acp_lifecycle.py
docs/v1/17-serial-task-plan.md
```

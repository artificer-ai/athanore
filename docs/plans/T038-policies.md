# T038 — Policies: permissions, elicitation, ask gating

**Task.** `docs/v1/17-serial-task-plan.md` § `### T038`.
**Specs.** `docs/v1/05-agents.md` §Policies;
`docs/v1/20-carried-findings.md` (the ACP permission findings the design
cites); `docs/v1/15-decisions.md` D10.
**Reference.** v0's `tests/test_permissions.py`, `test_elicitation.py`.

## What this task is

What happens when an agent asks for permission or raises an
elicitation — resolved either automatically by policy or by opening a
request for the operator.

## What this task is not

- No ACP wiring (T039 calls these) and no HTTP.
- No new request modes. Permissions are `options`; elicitations with a
  schema are `form`.
- An agent must never be able to widen its own policy.

## Steps

1. `choose_by_kind(options, kinds) -> str | None`.
2. `async resolve_permission(agent, ctx, tool_call, options) -> str`:
   - `auto_allow` → `allow_once`, then `allow_always`;
   - `auto_deny` → `reject_once`, then `reject_always`;
   - neither present → `AgentError`;
   - `ask` **outside** a task context → warn and fall back to
     `auto_allow` (the container is the guardrail there);
   - `ask` → `create_agent_request(mode=options, kind=permission,
     options verbatim, tool_call=<bounded summary: title, kind, first
     500 chars of raw input>)`, then `wait(timeout=agent.permission_timeout)`.
     The summary is bounded because a tool call's raw input can be a
     whole file;
   - on `TimeoutError` → `answer_as_engine` with the option chosen by
     kind for `permission_timeout_action`, so the record shows the
     engine answered rather than a human.
3. `async resolve_elicitation(agent, ctx, message, mode, requested_schema)`:
   `decline` policy or a URL mode → `("decline", None)`; a form → a
   `form` request with the schema and `json_schema_validator`
   registered, wait, `("accept", value)`; a timeout declines.
4. `ask_allowed(ctx) -> bool`.

## Verification

`tests/agents/test_policies.py`, porting the non-subprocess assertions:

- **reject-first ordering still picks `allow_once`** under `auto_allow` —
  the ordering bug this test exists to catch;
- an engine-authored timeout answer is recorded with author `engine`;
- URL-mode elicitation declines;
- `ask` with no context warns and allows.

## Done

- Tests pass.
- `**Status.** Done.` on `### T038`, in the same commit.

## Files

```
athanore/agents/policies.py
tests/agents/test_policies.py
docs/v1/17-serial-task-plan.md
```

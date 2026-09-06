# T045a — MCP server at `/mcp/agent`

**Task.** `docs/v1/17-serial-task-plan.md` § `### T045a`.
**Specs.** `docs/v1/08-api.md` §MCP; `docs/v1/19-agent-prompts.md` (tool
descriptions — reuse the wording); `docs/v1/15-decisions.md` D63.

## What this task is

The same agent surface, spoken as MCP: the tier T039b negotiates when an
agent advertises MCP over HTTP.

## What this task is not

- **Not a second contract.** Same endpoints, same rules, same auth —
  one wire contract (`AGENTS.md`). Anything an MCP tool can do, the HTTP
  route can do, identically.
- No task id parameters. The token identifies the task; a tool that took
  a task id would be a way to reach someone else's.

## Steps

1. `athanore/api/mcp.py`: an `mcp` SDK server (streamable HTTP) mounted
   as a sub-application at `/mcp/agent`, authenticated with T043's
   `task_auth`.
2. Tools per 08 §MCP: `get_task`, `append_log`, `submit_result`,
   `ask_operator`, `wait_answer`.
   - `submit_result`'s input schema is read from
     `engine.live.context_for(task).output_model` **at list-tools
     time**, falling back to a free object when none is declared; a
     misfit returns an `isError` result carrying `errors` and `schema`;
   - `ask_operator` is **present only** when the live context has
     `ask_policy == "http"` — absence is the enforcement, matching
     T045's 403.
3. OpenAPI lists the route under `agent` as opaque.

## Verification

`tests/api/test_mcp.py`, using the `mcp` Python client against the ASGI
app:

- list-tools reflects the declared model;
- `submit_result` success and misfit;
- `append_log` writes with author `agent`;
- a wrong token is refused;
- `ask_operator` is absent when the policy is off.

## Done

- Tests pass; snapshot updated.
- `**Status.** Done.` on `### T045a`, in the same commit.

## Files

```
athanore/api/mcp.py
athanore/api/app.py            (mount)
tests/api/test_mcp.py
tests/snapshots/openapi.json
docs/v1/17-serial-task-plan.md
```

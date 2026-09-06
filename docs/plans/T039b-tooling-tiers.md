# T039b — Tooling tiers in the façade

**Task.** `docs/v1/17-serial-task-plan.md` § `### T039b`.
**Specs.** `docs/v1/05-agents.md` §Tooling tiers;
`docs/v1/19-agent-prompts.md` (the per-tier blocks);
`docs/v1/15-decisions.md` D63.

## What this task is

Three ways for an agent to reach the task API — `http` (curl in the
prompt), `mcp` (an MCP server it can call), `native` (vendor tools) —
and the negotiation that picks one.

## What this task is not

- No vendor extension. `native` support for pi is T040a, in
  `examples/`.
- No new endpoints. The MCP mount is the same wire contract.
- Not a fourth rule: `tooling` is an attribute on the agent class, an
  existing seam.

## Steps

1. `ACPAgent.tooling`; in `run()` read `initialize`'s `mcpCapabilities`.
   `auto` → `mcp` when `http` is advertised, else `http`.
2. The `mcp` tier passes
   `mcp_servers=[McpServerHttp(name="athanore",
   url=f"{api_base}/mcp/agent",
   headers=[HttpHeader("X-Athanore-Token", token)])]` to `new_session`.
3. `render_prompt` emits the tool-agnostic core plus 19's tier block. In
   `mcp` and `native` the submission and ask blocks become the one-line
   variants **and the token is absent from the prompt entirely** — it
   travels in the MCP header instead. Assert that.
4. Policies: a permission request whose tool call names the `athanore`
   MCP server is answered `allow_once` under `ask` **without opening a
   request** — asking an operator whether the agent may talk to us is
   noise, but the exemption is narrow: it is that server by name, not
   any MCP server.

## Verification

`tests/agents/test_tooling.py`, on `FakeACPAgent`:

- `advertise_mcp` → the `mcp` tier, with the fake recording the server
  URL and the header;
- `mcp_calls` to `append_log` and `submit_result` land **through the
  real endpoint**, not a shortcut;
- no advertisement → the `http` tier with the curl block;
- the prompt contains no token in `mcp`/`native`;
- the athanore-server permission is auto-allowed while a filesystem
  permission still asks.

## Done

- Tests pass; the token-absence assertion is present for both tiers.
- `**Status.** Done.` on `### T039b`, in the same commit.

## Files

```
athanore/agents/acp.py
athanore/agents/base.py       (tier blocks)
athanore/agents/policies.py   (the athanore-server exemption)
tests/agents/test_tooling.py
docs/v1/17-serial-task-plan.md
```

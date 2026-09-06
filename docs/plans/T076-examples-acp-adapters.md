# T076 — Port `claude_acp` and `docker_acp`

**Task.** `docs/v1/17-serial-task-plan.md` § `### T076`.
**Specs.** `docs/v1/05-agents.md` §User-land adapters;
`docs/v1/15-decisions.md` D64, D67.

## What this task is

The two vendor adapters, both thin, both outside the package.

## What this task is not

- **No new sandbox image.** The task text's `examples/docker/` is
  superseded: `docker/dev` already is that image (D64), and
  `./scripts/agent.sh` already is the way in (D67). Do not build a
  second definition of the sandbox — say so in the report rather than
  quietly creating one.
- No Docker knowledge inside `athanore/`.

## Steps

1. `claude_acp`:
   `command=["npx","-y","@agentclientprotocol/claude-agent-acp@X.Y.Z"]`
   pinned, `model` only, `stats_provider=None` (Claude's adapter does
   not expose the session files pi does — omitting is correct; do not
   fabricate).
2. `docker_acp`: point at the dev stack —
   `command=["./scripts/agent.sh", "pi"]` — with
   `permission_policy="auto_allow"` (the container is the guardrail) and
   `public_url` set so the task API resolves from inside.

## Verification

```sh
./scripts/dev.sh "uv run pytest -q examples"
echo '{"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":1}}' \
  | ./scripts/agent.sh pi
```

Both adapters must import and finalize under `examples/tests`; the
handshake proves the command line the adapter uses is the one that
works.

## Done

- Both import and finalize; no second sandbox image created.
- `**Status.** Done.` on `### T076`, in the same commit.

## Files

```
examples/{claude_acp,docker_acp}/**
examples/tests/test_adapters.py
docs/v1/17-serial-task-plan.md
```

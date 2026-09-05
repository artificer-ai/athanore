# Athanore

Code-defined AI agent workflows over the
[Agent Client Protocol](https://agentclientprotocol.com) (ACP).

A workflow is a Python graph: decorated `async` functions are nodes, edges
are inferred from parameter names, and a node's return value picks the next
node. Inside a node you may await an ACP agent (pi, Claude Code, a container,
a stub), run deterministic Python (tests, linters, git), or ask a human. A
server runs many concurrent runs of many workflows under explicit capacity
limits, persists everything, and exposes it to an operator through a browser
SPA and a small CLI.

The product bet: **agents produce values, deterministic code makes
decisions.** An agent never moves a task. It submits a validated value and
the node body routes on it, so every edge a run traverses is code you can
read, test, and blame.

## Status

**Design complete, implementation starting.**

The full design is in [`docs/v1/`](docs/v1/README.md): twenty numbered
documents plus the imported design mock. The build order is
[`docs/v1/17-serial-task-plan.md`](docs/v1/17-serial-task-plan.md).
`main.py` and `pyproject.toml` are `uv init` placeholders that the first
scaffold tasks replace.

Contributors and coding agents: read [`AGENTS.md`](AGENTS.md) before
changing anything.

## The three rules

These are the whole authoring interface. Capability is added only by
attaching it to these seams, never by adding a fourth rule.

1. **The signature is the graph.** Positional parameters are edges to other
   nodes. A keyword-only parameter after `*` is the optional payload.
   Exactly one node is `start=True`.
2. **The return value is the routing.** A plain value with one successor
   auto-transitions. An edge ref (`return qa`) or called ref
   (`return qa(payload)`) transitions explicitly. A list of refs fans out.
   No successors means the branch completes, and the run completes when its
   last branch lands.
3. **The exception is the failure policy.** Raising fails the attempt; the
   engine applies retry, then dead-letter.

A node declared `join=True` closes a fan-out: it runs once, after every
branch has transitioned into it, with the branch values as its payload.

## What it looks like

Illustrative, against the API specified in
[`docs/v1/04-engine.md`](docs/v1/04-engine.md) and
[`docs/v1/05-agents.md`](docs/v1/05-agents.md):

```python
from athanore import ACPAgent, Workflow, human_input

wf = Workflow("feature_build")


class Builder(ACPAgent):
    command = ["npx", "pi-acp"]
    system_prompt = "You implement one feature in the repo at cwd. ..."


@wf.node(start=True)
async def plan(build, *, payload):
    result = await Builder().run(payload["description"])
    return result.output


@wf.node(retries=1, timeout=600)
async def build(test):
    await Builder().run("Implement the plan in the work log.")


@wf.node()
async def test(review, build):
    ok = await run_tests()            # deterministic: no agent involved
    return review if ok else build    # explicit routing


@wf.node()
async def review(build):
    answer = await human_input("Ship it?", options=["ship", "revise"])
    if answer == "revise":
        return build                  # loop back; returning nothing completes


if __name__ == "__main__":
    wf.run(port=4002, workers=1)
```

## Features

- **Engine.** Fan-out and fan-in, loop-backs, deterministic nodes, retries
  with dead-letter, restart recovery, named capacity pools, priorities,
  pause/resume, cancel, rerun, retry, move. Waiting on a human releases
  the worker slot.
- **Agents.** Any ACP agent as a class carrying its config. Kickoff prompts,
  structured submissions validated against a pydantic model with in-session
  repair turns, permission and elicitation policies, streamed output, env
  scrubbing, real-data-only stats.
- **Human in the loop.** One request object for permissions, elicitations,
  and node questions, answered from the SPA or CLI, durable across restarts.
- **One wire contract.** HTTP plus server-sent events. OpenAPI is generated
  from the code and a typed TypeScript client is generated from OpenAPI.
- **Plugins.** Workflows declare routes, actions, panels, and event
  handlers; the built-in operator views are plugins too. Custom UI is a web
  component.
- **Local first.** Loopback needs no login. Binding to a network turns on an
  operator token. Agents get a per-task token scoped to their own task.
- **Storage.** SQLite by default, Postgres optional, Alembic migrations,
  retention.

## Layout

```
athanore/        Python package: graph, engine, requests, agents, events,
                 store, plugins, api, cli, testing, web/dist
web/             SPA source (Vite + React + TypeScript), builds into athanore/web/dist
examples/        user-land workflows and vendor adapters (uv workspace member)
tests/           Python tests
docs/v1/         the design documents
```

See [`docs/v1/02-architecture.md`](docs/v1/02-architecture.md) for the
per-module breakdown and the layering rule.

## Development

Python 3.11+ with [uv](https://docs.astral.sh/uv/); Node with pnpm once the
`web/` scaffold lands.

```sh
uv sync --all-groups --all-extras
uv run pytest -q
uv run ruff check . && uv run pyright && uv run lint-imports
```

Once the SPA scaffold exists:

```sh
pnpm -C web install
pnpm -C web typecheck && pnpm -C web test && pnpm -C web build
```

The task plan is executed one task at a time, one commit per task, with the
commit message prefixed by the task id (`T012: ...`). Each task names the
spec sections that are its acceptance criteria.

# Athanore

Code-defined AI agent workflows over the
[Agent Client Protocol](https://agentclientprotocol.com) (ACP).

A workflow is a Python graph: decorated `async` functions are nodes, edges
are inferred from parameter names, and a node's return value picks the next
node. Inside a node you may await an ACP agent (pi, Claude Code, a
container, a fake), run deterministic Python (tests, linters, git), or ask a
human. A server runs many concurrent runs of many workflows under explicit
capacity limits, persists everything, and exposes it to an operator through
a browser SPA and a small CLI.

The product bet: **agents produce values, deterministic code makes
decisions.** An agent never moves a task. It submits a validated value and
the node body routes on it, so every edge a run traverses is code you can
read, test, and blame.

## Install

Python 3.11 or newer, with [uv](https://docs.astral.sh/uv/).

```sh
uv add athanore                # into a project that defines workflows
uv tool install athanore       # or just the CLI
uv add "athanore[postgres]"    # Postgres instead of the default SQLite
```

Athanore stores runs in SQLite in the directory it is started in and needs
nothing else: no service, no login, no API key until a workflow of yours
dispatches an agent that wants one.

**Version 1.0.0 is tagged** — `v1.0.0`, the last task of
[`docs/v1/17-serial-task-plan.md`](docs/v1/17-serial-task-plan.md). It is
tagged in this repository and nowhere else: there is no git remote and
nothing has been uploaded, so PyPI still carries the v0 MVP (`0.0.12`)
and the `uv add` lines above will fetch that until 1.0.0 is published.
Until it is, install v1 from a checkout — see
[Development](#development).

## A first workflow

Two nodes, no agents, so it runs with nothing configured. Save it as
`hello.py`:

```python
from athanore import Workflow, human_input

wf = Workflow("hello")


@wf.node(start=True)
async def greet(shout):
    name = await human_input("Who is this run for?")
    return shout(name)          # a called edge ref carries the payload


@wf.node()
async def shout(*, name):
    return {"greeting": f"HELLO {name.upper()}"}   # no edges: the run ends here
```

`greet` is the start node and `shout` is its one successor, because
`shout` is `greet`'s parameter. `shout` takes no edges of its own — only
the payload — so it is terminal, and what it returns is the run's output.
Waiting for the answer to `human_input` releases the worker slot, so a run
parked on a question does not hold the server.

Serve it, and drive it from a second shell:

```sh
athanore serve hello.py:wf          # http://127.0.0.1:4002, SPA and API
```

```sh
athanore submit hello "first run"   # → run id
athanore ls                         # runs, with the node each is on
athanore requests                   # what is waiting for you
athanore answer 1 world             # the request id, and the text typed
athanore show <run>                 # output: {'greeting': 'HELLO WORLD'}
```

...or open `http://127.0.0.1:4002`, submit from the command palette, and
answer the question in the inbox.

Nodes that dispatch an agent are the same shape. An agent is a class
carrying its own configuration, and its prompt is inlined text:

```python
from athanore import ACPAgent
from pydantic import BaseModel


class Verdict(BaseModel):
    ship: bool
    why: str


class Reviewer(ACPAgent):
    command = ["npx", "pi-acp"]           # any ACP adapter
    system_prompt = "You review one branch of one repository. ..."
    output_model = Verdict                # what the agent must submit


@wf.node(retries=1, timeout=1800)
async def review(merge, engineering):
    result = await Reviewer().run("Review the branch in the work log.")
    verdict: Verdict = result.output       # validated, or the run never got here
    return merge if verdict.ship else engineering
```

The agent submits a `Verdict` through the API and the node body routes on
it. It cannot move the task itself, and the branch that gets taken is the
`if` you just read.

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

## What it does

- **Engine.** Fan-out and fan-in, loop-backs, deterministic nodes, retries
  with dead-letter, restart recovery, named capacity pools, priorities,
  pause/resume, cancel, rerun, retry, move. Waiting on a human releases the
  worker slot.
- **Agents.** Any ACP agent as a class carrying its config. Kickoff prompts,
  structured submissions validated against a pydantic model with in-session
  repair turns, permission and elicitation policies, streamed output, env
  scrubbing, real-data-only stats. An agent reaches the API through MCP
  tools, a harness extension, or `curl`, with a token that reaches its own
  task and no other.
- **Human in the loop.** One request object for permissions, elicitations,
  and node questions, answered from the SPA or CLI, durable across
  restarts.
- **One wire contract.** HTTP plus server-sent events. OpenAPI is generated
  from the code and a typed TypeScript client is generated from OpenAPI.
- **Plugins.** Workflows declare routes, actions, panels, and event
  handlers; the built-in operator views are plugins too. Custom UI is a web
  component.
- **Local first.** Loopback needs no login. Binding to a network turns on
  an operator token. Agents get a per-task token, header-only, scoped to
  their own task.
- **Storage.** SQLite by default, Postgres optional, Alembic migrations,
  retention windows, and an importer for a v0 database.

## The CLI

```sh
athanore serve [module:wf ...] [--host] [--port] [--workers N] [--db URL] [--open]
athanore submit <workflow> "<title>" ["<description>"]
athanore ls | show <run> | logs <run> [-f] | stream <task> [-f] | workflows
athanore requests [run] | answer <req> <value> | permit <req> | deny <req>
athanore pause <run> | resume | cancel | rm | position <run> up|down|<index>
athanore rerun <run> <node> | retry <task> | move <task> <node>
athanore db upgrade | backup <path> | import-v0 <file>
athanore token show | rotate        athanore login <url>        athanore open
```

Every read verb takes `--json`, so the CLI composes with `jq`. Full
reference: [`docs/v1/11-cli.md`](docs/v1/11-cli.md).

Pools and per-workflow capacity come from an `athanore.toml` beside the
database:

```toml
[pools]
build = 2

[workflows.feature_build]
pool = "build"
```

## Layout

```
athanore/        Python package: graph, engine, requests, agents, events,
                 store, plugins, api, cli, server, testing, web/dist
web/             SPA source (Vite + React + TypeScript), builds into athanore/web/dist
examples/        user-land workflows and vendor adapters (uv workspace member)
tests/           Python tests
docs/v1/         the design documents; docs/plans/ the per-task plans
```

See [`docs/v1/02-architecture.md`](docs/v1/02-architecture.md) for the
per-module breakdown and the layering rule. Nothing in `athanore/` depends
on pi, Claude, or Docker: vendor adapters are user-land, in `examples/`.

## Development

Everything runs in the dev stack — one container image behind the gate, the
app, the SPA dev server and every agent — so the gate a human runs is the
gate an agent runs:

```sh
./scripts/test.sh                          # the gate: ruff, pyright, import-linter,
                                           # pytest, the SPA suites, the contract check
./scripts/run.sh                           # serve the app on 127.0.0.1:4002
./scripts/dev.sh                           # a shell in the container
./scripts/dev.sh "uv run pytest -q -k settings"
```

Or directly, with uv and pnpm on the host:

```sh
uv sync --all-packages --all-groups --all-extras
uv run pytest -q
uv run ruff check . && uv run pyright && uv run lint-imports
pnpm -C web install && pnpm -C web test && pnpm -C web build
```

`uv run athanore serve` then serves the workflows in `examples/`, which is
a workspace member and registers them as entry points.

## Documentation

- [`docs/v1/README.md`](docs/v1/README.md) — the twenty design documents,
  in reading order. They are the specification, not a description: MUST and
  SHOULD carry their RFC 2119 meanings.
- [`docs/v1/15-decisions.md`](docs/v1/15-decisions.md) — every decision
  and its reason.
- [`AGENTS.md`](AGENTS.md) — how to work in this repository. Read it before
  changing anything, human or agent.
- [`DESIGN.md`](DESIGN.md) — where the MVP's design document went.

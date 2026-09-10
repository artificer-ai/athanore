---
name: athanore-workflows
description: Write or change an Athanore workflow — nodes and inferred edges, routing by return value, failure and retry policy, agents, human input, fan-out and joins, pools. Load this before writing a workflow module, a node body or an agent class.
---

# Writing an Athanore workflow

A workflow is one Python module: a `Workflow` object and some `async`
functions decorated with `@wf.node()`. Three rules are the whole
authoring interface — the signature is the graph, the return value is
the routing, the exception is the failure policy — and everything else
attaches to them. This directory is self-contained: every file it
names is under its own `reference/`.

## A complete workflow

Two nodes, no agents, so it runs with nothing configured. Save it as
`hello.py`:

<!-- from: README.md -->
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
`shout` is `greet`'s parameter. `shout` takes no edges — only the
payload after `*` — so it is terminal, and what it returns is the run's
output. Serve it, and drive it from a second shell:

<!-- from: README.md -->
```sh
athanore serve hello.py:wf          # http://127.0.0.1:4002, SPA and API
```

<!-- from: README.md -->
```sh
athanore submit hello "first run"   # → run id
athanore ls                         # runs, with the node each is on
athanore requests                   # what is waiting for you
athanore answer 1 world             # the request id, and the text typed
athanore show <run>                 # output: {'greeting': 'HELLO WORLD'}
```

## The rules an agent gets wrong first

- **Positional parameters are edges; the keyword-only parameter after
  `*` is the payload.** `*args` and `**kwargs` are rejected. Exactly one
  node is `start=True`, and the graph is checked once, at registration.
- **Return an edge to move, call it to carry a payload, return a list to
  fan out, return an empty list to end the branch.** A plain value from
  a node with one edge goes along it; from a node with no edges it is
  the branch's result; from a node with two or more edges it is an
  error — the engine does not guess.
- **`NonRetryable` and `GraphError` dead-letter at once; anything else
  is retried** up to the node's `retries` and then dead-lettered.
- **Never write a retry loop around an agent call.** Retrying is the
  engine's job, and a body that does it too takes that budget away.
- **A node `timeout` caps one attempt of the body and its clock stops
  while a person is being waited on.** An agent's own timeout does not
  stop, because the agent process is alive throughout.
- **`join=True` closes a fan-out**: the node runs once, after every
  branch has arrived, with one entry per branch in its payload slot. A
  join node has to declare a payload slot, and it waits for every
  branch — there is no timeout and no "first N of M".
- **An agent submits a value; the body routes on it.** An agent cannot
  transition a task or choose a node. `output_model` makes
  `result.output` a validated instance of your model, or the body never
  got there; `result.ok` is false for a refusal or a truncated turn, and
  a transport failure raises `AgentError`.
- **`human_input(prompt)` returns text, `options=[...]` returns the
  option picked, `output_model=Model` returns an instance** — and the
  worker slot goes back to the pool while the body waits.
- **In tests, replace the agent with `MockAgent`** from
  `athanore.testing`: `output=` is the shortest double, `submit=` makes
  the real round trip, `fail=` raises what a body has to route around.
- A workflow is registered on exactly one pool, and a workflow name may
  not be a verb of the command line.

## Where to read next

Every file below is in this skill's `reference/`. The guides are
narrative; the four after them are generated from the code, so a
default there is the default that runs.

- How routing works in full, fan-out and joins, output, registering and
  serving: `reference/guide-workflows.md`.
- Agent classes, inlined prompts, structured submissions, how an agent
  reaches its task, permissions and elicitations, stats, testing without
  a model, vendor adapters: `reference/guide-agents.md`.
- Asking a person from a body, what the wait does to the slot, and how
  an answer is claimed once: `reference/guide-human-in-the-loop.md`.
- Pools and capacity, dispatch order, retries and dead-letter, steering
  a run, restart recovery: `reference/guide-runs.md`.
- Every name the package exports, with its signature:
  `reference/python-api.md`.
- Every `@wf.node()` option and every `Pool` field, with defaults:
  `reference/node-options.md`.
- Every attribute an `Agent` or `ACPAgent` subclass may set, and the
  fields of `AgentResult`: `reference/agents.md`.
- Every event name and the payload it carries: `reference/events.md`.

A workflow's own routes, actions and panels are the `athanore-plugins`
skill; the command line that serves it is the `athanore-cli` skill.

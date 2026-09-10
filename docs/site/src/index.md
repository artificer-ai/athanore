# Athanore

Athanore is an orchestrator for code-defined AI agent workflows over the
[Agent Client Protocol](https://agentclientprotocol.com).

A workflow is a Python graph. Decorated `async` functions are nodes,
the edges are read off their parameter names, and what a node returns
picks the node that runs next. Inside a node you can await an ACP agent
(pi, Claude Code, one in a container, a fake), run ordinary deterministic
Python — tests, linters, `git` — or stop and ask a person. A server runs
many concurrent runs of many workflows under explicit capacity limits,
persists all of it, and shows it to you through a browser interface and a
small command line.

## The bet

**Agents produce values; deterministic code makes decisions.**

An agent never moves a task. It submits a value, that value is validated
against a model you declared, and then your node body — plain Python you
can read, test and blame — decides where the work goes. Every edge a run
traverses is an `if` somebody wrote.

That is the whole difference between this and a prompt chain. When a run
takes a branch you did not expect, the explanation is in a function, not
in a transcript.

## The three rules

These are the entire authoring interface, and there is deliberately never
a fourth.

1. **The signature is the graph.** A node's positional parameters name
   the nodes it can hand work to, so the edges come from the function
   rather than from a separate declaration. A keyword-only parameter
   after `*` is the payload it receives. Exactly one node starts.
2. **The return value is the routing.** Returning an edge reference
   transitions along it; calling one (`return qa(payload)`) carries a
   payload with it; returning a list of them fans out. A plain value with
   one successor goes along it. No successors means the branch is done,
   and the run completes when its last branch lands.
3. **The exception is the failure policy.** Raising fails the attempt.
   The engine then applies retries and, when those run out, dead-letters
   the task. Retrying is the engine's job, never the body's.

New capability attaches to one of the existing seams — options on a node,
an object you await inside a body, a declaration the workflow carries.

```python
from athanore import Workflow, human_input

wf = Workflow("hello")


@wf.node(start=True)
async def greet(shout):
    name = await human_input("Who is this run for?")
    return shout(name)


@wf.node()
async def shout(*, name):
    return {"greeting": f"HELLO {name.upper()}"}
```

`greet` starts, `shout` is its one successor because `shout` is `greet`'s
parameter, and `shout` has no edges of its own, so what it returns is the
run's output.

## What you get

- **An engine.** Fan-out and fan-in, loop-backs, deterministic nodes,
  retries with dead-letter, recovery after a restart, named capacity
  pools, priorities, pause, resume, cancel, rerun, retry and move.
  Waiting on a person gives the worker slot back.
- **Agents as classes.** Any ACP agent, configured by a class that
  carries its own prompt, its structured output model, its permission and
  elicitation policies, its timeout and its working directory. Output is
  streamed, token counts and cost are recorded when the provider reports
  them, and never invented when it does not.
- **A human in the loop.** One request object covers permission prompts,
  elicitations and questions a node asks, answerable from the browser or
  the terminal, and durable across a restart.
- **One wire contract.** HTTP plus server-sent events, with an OpenAPI
  document generated from the code and a typed TypeScript client
  generated from that.
- **Plugins.** A workflow declares its own routes, actions, panels and
  event handlers, and the built-in operator views are declared the same
  way.
- **Local first.** A loopback bind needs no login at all. Binding to a
  network turns on an operator token. Agents get a token scoped to one
  task.

## Where to go next

- [Install](install.md) — one command, and what a fresh install needs.
- [Quickstart](quickstart.md) — a two-node workflow, served, submitted
  and answered.
- [Writing a workflow](guide/workflows.md) — nodes, routing, fan-out and
  joins.
- [Python API](reference/python-api.md) — every name the package
  exports, generated from the code.

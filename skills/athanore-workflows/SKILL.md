---
name: athanore-workflows
description: Write or change an Athanore workflow — nodes and inferred edges, routing by return value, failure and retry policy, agents, human input, fan-out and joins, pools. Load this before authoring a workflow module, a node body or an agent class, to find which design document settles the behaviour and which shipped workflow to copy.
---

# Writing an Athanore workflow

Every path in this file is relative to the **checkout root**: the
directory two levels above this file in the checkout this skill was
installed from. Nothing here is normative — `docs/v1/` is the
specification and this only says which part of it to open.

## The surface

A workflow is one Python module: a `Workflow` object and some functions
decorated with `@wf.node()`. Three rules are the whole authoring
interface, and there is deliberately never a fourth
(`docs/v1/01-vision-and-scope.md` §The three rules (unchanged)):

1. **The signature is the graph.** A node's parameters are the nodes it
   may hand work to, so the edges are read off the function rather than
   declared. See `docs/v1/04-engine.md` §Signature parsing (unchanged semantics).
2. **The return value is the routing.** What a body returns says where
   the work goes next and what it carries; returning something that is
   not an edge ends that branch. See `docs/v1/04-engine.md` §Routing interpretation,
   and — for the forms that are easy to get wrong —
   `docs/v1/04-engine.md` §Routing edge cases.
3. **The exception is the failure policy.** Raising is how a body says
   the attempt failed, and which exception it raises decides whether the
   engine tries again: `docs/v1/04-engine.md` §Failure classes (rule 3, refined).
   Retries belong to the engine — never write one into a node body on
   its behalf.

Capability is added by attaching it to a seam below. If you find
yourself wanting a fourth rule, you have found a seam you have not read
yet.

## The seams

- **Node options** — the metadata a node carries, given to the
  decorator: `docs/v1/04-engine.md` §Node options (metadata seam).
  Which options exist, with their types and defaults, is
  `skills/athanore-workflows/reference/node-options.md`.
- **`join=True`** — a node that waits for a fan-out to arrive rather
  than for one predecessor: `docs/v1/04-engine.md` §Fan-in (join nodes).
- **Pools and priority** — the capacity a workflow's work is dispatched
  against, and the order within it: `docs/v1/04-engine.md` §Pools,
  and `docs/v1/04-engine.md` §Dispatch order (per pool).
- **An object awaited inside a body** — where most new capability goes,
  and there are three of them: an agent
  (`docs/v1/05-agents.md` §Agent classes), a question for the operator
  (`docs/v1/06-requests.md` §The model), and the narrow services on the
  task context (`docs/v1/04-engine.md` §TaskContext).
- **Declarations the workflow carries** — routes, actions, panels and
  event handlers, which is how a workflow ships its own UI. That is a
  surface of its own: `skills/athanore-plugins/SKILL.md`.
- **The host** — `wf.run()` for one workflow, a `Server` for several:
  `docs/v1/04-engine.md` §Programmatic host. The command line that does
  the same thing is `skills/athanore-cli/SKILL.md`.

## Where to read

| If you are asking | Open |
|---|---|
| how are edges inferred from a signature? | `docs/v1/04-engine.md` §Signature parsing (unchanged semantics) |
| what may a body return, and what does each form do? | `docs/v1/04-engine.md` §Routing interpretation |
| what happens on an empty return, a duplicate edge, a payload that is not a mapping? | `docs/v1/04-engine.md` §Routing edge cases |
| when is a graph rejected, and when is that noticed? | `docs/v1/04-engine.md` §Finalization |
| what happens when a node raises, and what does `NonRetryable` change? | `docs/v1/04-engine.md` §Failure classes (rule 3, refined) |
| which clock does a node timeout use, and what error does it raise? | `docs/v1/04-engine.md` §Timeouts (which clock, which error) |
| how do I fan out and join? | `docs/v1/04-engine.md` §Fan-in (join nodes) |
| what does a body get from its task context? | `docs/v1/04-engine.md` §TaskContext |
| how do I ask a human, and what happens to the worker slot while I wait? | `docs/v1/04-engine.md` §Waiting on a human (new) |
| what shape may an answer take, and where can it be answered from? | `docs/v1/06-requests.md` §The model |
| which surfaces can answer a question? | `docs/v1/06-requests.md` §Surfaces |
| how do I declare an agent? | `docs/v1/05-agents.md` §Agent classes |
| what does `output_model` buy me? | `docs/v1/05-agents.md` §Submissions |
| what does one agent run return? | `docs/v1/05-agents.md` §AgentResult |
| how does an agent reach its own task? | `docs/v1/05-agents.md` §Tooling tiers: how an agent reaches its task |
| what happens when an agent asks for a permission? | `docs/v1/05-agents.md` §Policies |
| what does the agent actually receive as its prompt? | `docs/v1/19-agent-prompts.md` §Assembly |
| what do I get in the way of token counts and cost? | `docs/v1/05-agents.md` §Stats entry |
| how do I run a workflow without a model in the loop? | `docs/v1/05-agents.md` §Testing doubles (`athanore.testing`) |
| what does a test of this look like? | `docs/v1/13-testing.md` §Fakes |
| at which layer does that test belong? | `docs/v1/13-testing.md` §Pyramid |

Two things to get right the first time, both of which the documents
above say plainly: **an agent never moves a task** — it submits a value
and the node body routes on it — and a body never retries an agent call
on the engine's behalf, because retrying is rule 3's job.

## What to copy

- `README.md` §A first workflow. Two nodes, no agents, and it runs with
  nothing configured.
- `workflows/rps.py` — the smallest complete workflow in the tree: a
  question for the operator, a loop-back edge, a real output, no agent
  anywhere.
- `workflows/feature/` — the multi-node workflow with agents, a join,
  pools and plugins that builds this repository. The best worked example
  of everything at once.
- `examples/pi/agent.py`, `examples/claude_acp/`, `examples/docker_acp/`
  — vendor `ACPAgent` subclasses. They are user-land by design, kept as
  examples rather than shipped in the package:
  `docs/v1/05-agents.md` §User-land adapters (examples, not shipped).
- `athanore/testing/` — the doubles CI runs behind every agent.

`workflows/` is this repository's own operating workflows; `examples/`
is a distribution, a workspace package of its own.

Rule 1 taken literally, from `workflows/rps.py` — a node naming itself
as one of its own edges, so the engine walks the loop as a fresh task
each time round:

<!-- from: workflows/rps.py -->
```python
@wf.node(retries=0, timeout=None)
async def play(play, tally, *, payload):
```

## Generated reference

Facts, read off the code by `scripts/gen_skills.py`, so they cannot
drift from it:

- `skills/athanore-workflows/reference/public-api.md` — every name
  `athanore` exports.
- `skills/athanore-workflows/reference/node-options.md` — the node
  options and the fields of a pool.
- `skills/athanore-workflows/reference/agents.md` — what an agent
  subclass may set, and what a run returns.
- `skills/athanore-workflows/reference/events.md` — the event
  vocabulary and the payload each name carries.

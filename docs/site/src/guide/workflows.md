# Writing a workflow

A workflow is one Python module: a `Workflow` object and some `async`
functions decorated with `@wf.node()`. Three rules are the whole
authoring interface.

```python
from athanore import Workflow

wf = Workflow("feature_build")


@wf.node(start=True)
async def prompt(product):
    ...


@wf.node(retries=1, timeout=600)
async def product(architecture):
    ...


@wf.node()
async def architecture(engineering, *, deliverable):
    ...


@wf.node()
async def engineering():
    ...
```

## Rule 1: the signature is the graph

A node's positional parameters name the nodes it can hand work to. There
is no separate edge declaration, and there is no way for the graph and
the code to disagree, because they are the same text.

The payload slot is the exception. A keyword-only parameter, the first
one after `*`, receives whatever the previous node sent, rather than
being an edge. If the signature uses a `/`, the first parameter after
it is the payload instead. `*args` and `**kwargs` are rejected.

Exactly one node is `start=True`. The graph is checked once, when the
workflow is registered. A missing or duplicated start node, an edge
naming a node that does not exist, a duplicate node name, a node nothing
can reach from the start, or a workflow name that is not a Python
identifier all raise `GraphError` there rather than mid-run.

## Rule 2: the return value is the routing

What a body returns says where the work goes and what it carries.

```python
from athanore import Workflow

wf = Workflow("routing")


@wf.node(start=True)
async def decide(review, ship, *, payload):
    if payload["urgent"]:
        return ship                     # an edge reference: transition
    return review({"diff": payload})    # a called reference: transition with a payload


@wf.node()
async def review(ship, *, diff):
    return ship                         # loop-backs are ordinary edges


@wf.node()
async def ship(*, payload):
    return {"shipped": True}            # no edges: this branch is terminal
```

The forms, in short:

- an edge reference, or a called one, transitions along that edge;
- a non-empty list of references or transitions fans out, one branch
  each;
- an empty list or tuple ends this branch, whatever edges the node
  declares;
- anything else, from a node with no edges, ends the branch, and when it
  is the last branch, that value is the run's output;
- anything else, from a node with exactly one edge, goes along it as the
  next node's payload;
- anything else, from a node with two or more edges, is an error: the
  engine will not guess which one you meant.

Payloads are converted to JSON-able values on the way out, so a pydantic
model or a dataclass arrives as a dictionary.

## Rule 3: the exception is the failure policy

Raising is how a body says the attempt failed. The exception *type*
picks between the two policies the engine has:

- `GraphError`, raised for routing to an edge that was never declared or
  for an ambiguous plain return, dead-letters immediately. Retrying
  would reproduce a code defect.
- `NonRetryable`, which your body raises deliberately, dead-letters
  immediately too. Use it when you already know a second attempt cannot
  help: a refusal, a hard validation failure.
- Anything else, including the `asyncio.TimeoutError` a node `timeout`
  raises, is retried up to the node's retry count and then
  dead-lettered.

Never write a retry loop around an agent call. Retrying is rule 3's job,
and a body that does it too takes the engine's budget away from it.

## Node options

The decorator carries the node's metadata: whether it starts the
workflow, how many retries it gets, a wall-clock cap on one attempt, an
explicit dispatch priority, whether it closes a fan-out, and the label
and description the graph view shows. The exact names, types and
defaults are in [Node options](../reference/node-options.md).

`timeout` is a cap on one attempt of the *body*, and its clock stops
while the task is waiting on a person. A human taking a day should not
fail an attempt budgeted for ten minutes of agent time. An agent has a
timeout of its own, which does count the wait, because the agent process
is alive throughout.

## Fan-out and join

Returning a list of transitions splits the work:

```python
from athanore import Workflow

wf = Workflow("fanout")


@wf.node(start=True)
async def plan(build, *, payload):
    return [build(item) for item in payload["items"]]     # one branch per item


@wf.node()
async def build(release, *, item):
    return release({"item": item, "ok": True})


@wf.node(join=True)
async def release(*, results):
    # runs once, after every branch has arrived
    return {"released": [r["value"] for r in results]}
```

A node declared `join=True` closes a fan-out. It dispatches once, after
every branch has transitioned into it, and its payload slot receives one
entry per branch in fan-out order. Each entry carries the branch's
index, the payload that identified it, the value that arrived and the
task it came from. A join node has to declare a payload slot; one that
does not is rejected when the graph is checked.

A join waits for every branch. There is no timeout on one and no
"first N of M". A branch that is stuck is an operator problem, and retry,
move and cancel are the tools for it. If a run ends up with nothing to
do and a join that only partly arrived, that is reported as a failure
naming the join and the count, not as a completion.

Branches nest. A branch that fans out again pushes another frame, and an
inner join closes the inner fan-out first.

## Run output

A run completes when its last branch lands. If exactly one task was
terminal, as in a linear workflow or a fan-out closed by a join, that
task's value is the run's output. If several branches ended
independently, the output is the list of their values in branch order.
Closing a fan-out with a join is the recommended shape, because then
there is one answer rather than a list.

## Registering and serving workflows

The shortest form runs one workflow:

```python
from athanore import Workflow

wf = Workflow("hello")


@wf.node(start=True)
async def only():
    return {"done": True}


if __name__ == "__main__":
    wf.run()
```

For several workflows, or explicit capacity, build the server yourself:

```python
from athanore import Pool, Server

from myproject.flows import gamedev, feature_build


def main() -> None:
    server = Server()                                  # settings from env and file
    server.register(feature_build, Pool("local", 1))
    server.register(gamedev, Pool("local", 1))
    server.serve()
```

Both are the same thing the command line does. The `athanore serve`
form, which also reads pools from a configuration file and finds
installed workflows, is in [Using the command line](cli.md).

Registration does not stop when serving starts. `register` is for
before `start()`. On a serving server the same host awaits three verbs,
`add`, `replace` and `remove`, which register a workflow, swap its
graph and plugins under the same name, or drop it, without a restart
and without touching the other workflows' runs:

```python
await server.add(chat, target="workflows/chat.py:wf", persist=True)
await server.replace(chat)          # the next task of every run dispatches on the new graph
removed = await server.remove("chat")
removed.task_ids                    # the attempts that were interrupted
```

`persist=True` writes the registration as a `[workflows.chat]` row of
`athanore.toml` (see [Deployment](deployment.md)), and
`server.register_configured()` before `start()` is how a programmatic
host loads such rows back. An attempt already running finishes on the
body it started with. A removed workflow's runs stay listed, flagged
`unregistered`, and resume when it is added back. The dashboard follows
all three without a page reload: the library, the new-run chips, the
pane bar and the run rows move as the registration does. When a
plugin's JavaScript has changed under it, the dashboard shows a reload
notice rather than pretending, because a module a page has already run
cannot be run again.

The same three verbs are on the wire and on the command line, so an
agent or a script can do what the host does. `POST /api/workflows`
with a target registers one, `PUT /api/workflows/{name}` reloads one,
and `DELETE /api/workflows/{name}` drops it; `athanore workflows add`,
`reload` and `rm` do the same (see [Using the command line](cli.md)). A
target that does not load is answered `422 workflow_load_failed`, and
the field to read in that body is `stage`: `target` (the string is not
`where:attr`), `import` (the file would not load), `attribute` (no such
attribute, or not a workflow), `finalize` (the graph does not close),
`plugins` (a declaration does not validate) or `register` (the name is
a verb or a pool). `detail` is the underlying error, in full.

## Next

- [Dispatching agents](agents.md): the object most bodies await.
- [Asking a human](human-in-the-loop.md): the other one.
- [Runs, retries and capacity](runs.md): what happens to a node once
  the graph is written.

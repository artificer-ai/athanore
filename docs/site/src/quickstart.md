# Quickstart

A two-node workflow, end to end: written, served, submitted, answered
and read back. It uses no agent, so it runs with nothing configured.

## Write it

Save this as `hello.py`:

```python
from athanore import Workflow, human_input

wf = Workflow("hello")


@wf.node(start=True)
async def greet(shout):
    name = await human_input("Who is this run for?")
    return shout(name)          # a called edge reference carries the payload


@wf.node()
async def shout(*, name):
    return {"greeting": f"HELLO {name.upper()}"}   # no edges: the run ends here
```

Two things are happening, and they are rules 1 and 2.

`greet` takes one positional parameter, `shout`, so `shout` is the one
node `greet` can hand work to — that is the edge. What arrives in the
body is an edge reference, and calling it (`shout(name)`) returns a
transition that carries `name` as the next node's payload.

`shout` takes no positional parameters at all, only the keyword-only
payload slot after `*`. It has no successors, so it is terminal, and the
dictionary it returns becomes the run's output.

`human_input` parks the body until you answer. While it waits, the task
gives its worker slot back, so a run stopped on a question does not hold
the server.

## Serve it

```sh
athanore serve hello.py:wf
```

That prints a URL — `http://127.0.0.1:4002` by default. The browser
interface and the HTTP API are both there, the database is
`athanore.db` in the current directory, and the bind is loopback, so
there is no token and no login.

## Drive it from a terminal

In a second shell:

```sh
athanore submit hello "first run"   # prints a run id
athanore ls                         # every run, and the node each is on
athanore requests                   # what is waiting for you
athanore answer 1 world             # the request id, then what you are answering
athanore show <run>                 # output: {'greeting': 'HELLO WORLD'}
```

`athanore ls` shows the run sitting on `greet`, waiting. `athanore
requests` shows the question. Answering it wakes the body, `greet`
returns `shout("world")`, `shout` runs and the run completes.

Every read verb takes `--json`, so this composes with `jq`:

```sh
athanore ls --json | jq '.[] | {id, status, node}'
```

## ...or from the browser

Open `http://127.0.0.1:4002`. Press `Ctrl-P` (or `⌘P`) for the command
palette and submit a run from there; the question appears in the inbox and can be
answered in place. The run's graph, its work log, its events and any
agent transcript are all on the run's page.

## Add an agent

A node that dispatches an agent is the same shape. An agent is a class
that carries its own configuration and its own prompt as inlined text,
and `output_model` is what turns its answer into a validated Python
object:

```python
from athanore import ACPAgent, NonRetryable, Workflow
from pydantic import BaseModel

wf = Workflow("review")


class Verdict(BaseModel):
    ship: bool
    why: str


class Reviewer(ACPAgent):
    command = ["npx", "-y", "pi-acp@0.0.33"]     # any ACP adapter
    system_prompt = "You review one branch of one repository. ..."
    output_model = Verdict                       # what the agent has to submit


@wf.node(start=True, retries=1, timeout=1800)
async def review(merge, rework):
    result = await Reviewer().run("Review the branch in the work log.")
    if not result.ok:
        raise NonRetryable(result.error)
    verdict: Verdict = result.output             # validated, or we never got here
    return merge if verdict.ship else rework


@wf.node()
async def merge():
    ...


@wf.node()
async def rework():
    ...
```

The agent submits a `Verdict` through the API; the node body routes on
it. The agent cannot move the task, and the branch that gets taken is the
`if` you just read.

## Next

- [Writing a workflow](guide/workflows.md) — routing in full, fan-out,
  joins and loop-backs.
- [Dispatching agents](guide/agents.md) — prompts, submissions, repair
  turns, policies and stats.
- [The command line](guide/cli.md) — every verb, and how one finds a
  server.

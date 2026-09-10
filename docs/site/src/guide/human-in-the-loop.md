# Asking a human

Everything that blocks on a person is one object: a request. A node
asking a question, an agent asking permission to run a tool, and an agent
asking for structured input are all the same row, answerable from the
same places, and durable across a restart.

## From a node body

```python
from athanore import Workflow, human_input
from pydantic import BaseModel

wf = Workflow("ask")


class Release(BaseModel):
    version: str
    notes: str = ""


@wf.node(start=True)
async def confirm(ship, hold):
    answer = await human_input(
        "Ship this build?",
        options=["ship", "hold"],
    )
    return ship if answer == "ship" else hold


@wf.node()
async def ship(*, payload):
    details = await human_input("Release details", output_model=Release)
    return {"version": details.version}


@wf.node()
async def hold():
    ...
```

Three shapes, and the argument you pass decides which:

- plain `human_input(prompt)` asks for text and returns a string;
- `options=[...]` asks you to pick one and returns the option you picked;
- `output_model=Model` renders a form from the model's schema, validates
  what you type against it, and returns an instance.

`timeout=` bounds the wait and raises `TimeoutError` into the body, which
then decides what that means. Without one, the request waits
indefinitely, which is usually what you want.

## Waiting gives the slot back

This is the part that matters for throughput. While a node is parked on
`human_input` the task is marked as waiting and its worker slot goes back
to the pool, so other runs keep moving. When you answer, the task joins
the front of that pool's queue — it is mid-execution and holding state,
and it already queued once — and the body resumes where it stopped.

The node's own timeout clock is paused for the duration. A person taking
a day does not fail an attempt budgeted for ten minutes of agent work. To
bound the wait itself, pass `timeout=` to `human_input`.

Agent-side waits are different: a permission prompt or an elicitation
keeps the slot, because the agent process is alive and holding
inference-adjacent resources.

## From an agent

Two of the three producers are the agent's, and neither needs anything in
your body:

- a **permission** request, opened when an agent asks to run a tool and
  the class's `permission_policy` is `ask`. Your answer goes back to the
  agent as its own protocol response, with the agent's own options
  offered verbatim.
- an **elicitation**, when an agent asks for structured input. The
  agent's schema becomes the form, and the answer is validated against it
  before it is sent back.

An agent class with `ask_policy="http"` can also ask a plain question of
its own. It is off by default.

Whichever the producer, the answer is a *value*. A node's answer feeds
deterministic Python that routes; an agent's answer feeds a
probabilistic process mid-turn. Neither can move the graph.

## Answering

From the browser, open requests appear in an inbox, and the run that owns
one is marked. A request on the task you are watching gets a panel under
the agent transcript: buttons for an options request, an input for text,
a generated form for a schema.

From a terminal:

```sh
athanore requests            # everything waiting, across runs
athanore requests <run>      # just this run's
athanore answer 12 ship      # the request id, then the answer
athanore permit 13           # a permission request: allow
athanore deny 13             # ...or refuse
```

`answer` reads its argument against the request's mode, which is the one
fact that is not a guess: a form request takes JSON that parses as an
object, an options request takes an option, and a text request takes the
characters you typed — so an answer that happens to look like JSON still
reaches a text question as the string it is.

Request ids are unique across runs, so the run id is never needed to
answer one.

## Durability

Each request is a row, and one answer is claimed exactly once by the
waiter that opened it. There is no queue of untargeted answers and no
first-come ordering to reason about.

If the server restarts while a run is parked, the task is reset to ready
and the body re-executes; when it reaches the same `human_input` call it
finds the request it opened last time and takes the stored answer, or
parks again. It does not ask twice.

Answering a run that is paused resumes the body; its successors wait for
the run to be resumed, as they would anyway.

## Next

- [Runs, retries and capacity](runs.md) — what the pool is doing with
  that slot.
- [The command line](cli.md) — the answering verbs in full.

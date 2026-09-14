"""The workflows the Playwright suite drives (T068a, 13 §Pyramid).

Six of them, and between them they are every shape the E2E specs need:

- :data:`probe` is the run the suite watches from `submit` to
  `completed` — an agent that asks for permission to make a tool call,
  then a node that asks the operator a question, then a terminal node.
  It is the one workflow with an agent in it, and the agent is
  ``FakeACPAgent``: ``ATHANORE_AGENT_COMMAND`` replaces
  :attr:`~athanore.ACPAgent.command` for every façade in the process (13
  §Running examples on the fake), and ``ATHANORE_FAKE_SCENARIOS`` points
  at ``scenarios/``, where one file per node scripts what it does. No
  model is ever in the loop.
- :data:`spread` is a fan-out closed by a join. One branch stops to ask
  the operator a question, so the join sits at `k of n` for as long as
  the spec needs to read it, and answering finishes the run.
- :data:`hold` is a run that does not finish: one node that sleeps until
  the server stops. With the default pool at one worker it is how the
  suite gets a queue — a second and a third submission stay ``queued``,
  which is what `pause`, `resume` and `reorder` act on.

- :data:`flop` is the run that does not survive its first node: one
  node that raises with ``retries=0``, so the attempt dead-letters at
  once and the run reaches ``failed`` (04 §Retries, 03 §State machines).
  It is what puts the `fail` tone of 10 §Status colours on a row, which
  is the tone the a11y gate needs in the list — the pill is transparent
  over the selected row's tint, so `fail`, the darkest tone, is the one
  that decides whether the two are compatible (`a11y.spec.ts`, D204 (5)).

- :data:`ladder` is a chain of eight nodes, and its only job is to be
  tall. Eight ranks do not fit a 320 px canvas at the zoom the
  interaction floor allows, so it is what proves that the graph pane's
  fit has a floor of its own below the ``md`` breakpoint, where there is
  no pan and no zoom to recover a clipped picture with (D206 (7),
  `mobile.spec.ts`). Nothing in it waits, so a run of it is complete by
  the time the graph is read.

- :data:`plugged` is the plugin host of 09 §Escape hatch: a workflow
  that ships a static ES module (``static/playfield.js``) and declares a
  ``custom`` pane for the element that module defines. It is what
  ``plugin.spec.ts`` mounts, and the only fixture whose behaviour is in
  JavaScript rather than in Python — which is the point of it, since
  what T071 built is the seam between the two.

They live here rather than in ``examples/`` because they are fixtures of
this suite, answerable to what a test needs rather than to what an
example should show. `examples/` now carries the vendor adapters and
nothing else (D212), so there is no workflow there for these to be
replaced by.
"""

from __future__ import annotations

import asyncio

from athanore import ACPAgent, PluginContext, Workflow, human_input

__all__ = [
    "Builder",
    "FLOP_ERROR",
    "HOLD_SECONDS",
    "QUESTION",
    "PLAYFIELD_WORD",
    "flop",
    "hold",
    "ladder",
    "plugged",
    "probe",
    "spread",
]

#: What :data:`probe` asks the operator, and what the spec looks for.
QUESTION = "Ship it?"

#: What :data:`plugged`'s route answers with, and what the element it
#: mounts puts on screen. The spec looks for it, which is how "the
#: element fetched through `window.athanore`" is asserted rather than
#: assumed.
PLAYFIELD_WORD = "athanor"

#: What :data:`flop`'s one node raises, and what the run's error reads.
FLOP_ERROR = "the fixture that fails"

#: How long :data:`hold`'s one node sleeps. Longer than any run of the
#: suite: the point of the node is that it never finishes on its own, and
#: the engine cancels it when the server stops.
HOLD_SECONDS = 3600.0


class Builder(ACPAgent):
    """The suite's one agent façade.

    It declares no ``command`` of its own on purpose: the class is what
    a real workflow's agent looks like, and ``ATHANORE_AGENT_COMMAND`` —
    the setting that exists for exactly this (05, 13 §Running examples on
    the fake) — is what puts the fake behind it. A suite that hard-coded
    the fake here would be testing a different object from the one an
    operator runs.

    ``permission_policy`` stays at its default ``ask``, which is what
    sends the fake's tool call to the operator as a request (05
    §Policies), and ``permission_timeout`` stays ``None``, so the
    question waits for a person rather than for a clock.
    """


def _probe() -> Workflow:
    """Draft with an agent, ask the operator, ship.

    The shape of 17 §T068a's first spec: submit, watch the graph, allow
    the permission the agent asks for, answer the `human_input`, and
    reach ``completed``.
    """

    wf = Workflow("probe")

    @wf.node(start=True)
    async def draft(check):
        """Run the agent, then send its work to be checked."""

        await Builder().run()
        return check

    @wf.node()
    async def check(ship, shelve):
        """Ask the operator where the work goes."""

        if await human_input(QUESTION, options=["ship", "shelve"]) == "ship":
            return ship
        return shelve

    @wf.node()
    async def ship():
        return "shipped"

    @wf.node()
    async def shelve():
        return "shelved"

    return wf


def _spread() -> Workflow:
    """Two branches into one join, with the second branch stopping to ask.

    The join therefore reports `1 of 2 arrived` — the `k of n` of 10
    §Graph pane — until the operator answers, and the run completes once
    they do.
    """

    wf = Workflow("spread")

    @wf.node(start=True)
    async def split(build):
        return [build("alpha"), build("beta")]

    @wf.node()
    async def build(release, *, item):
        if item == "beta":
            await human_input(f"Approve {item}?", options=["approve"])
        return release({"built": item})

    @wf.node(join=True)
    async def release(*, results):
        return {"built": [result["value"]["built"] for result in results]}

    return wf


def _hold() -> Workflow:
    """One node that sleeps, so a run stays in flight and a queue forms."""

    wf = Workflow("hold")

    @wf.node(start=True)
    async def wait():
        await asyncio.sleep(HOLD_SECONDS)
        return "held"

    return wf


def _flop() -> Workflow:
    """One node that raises and is not retried, so the run fails.

    ``retries=0`` is the node option of 04 §Node options: the attempt
    dead-letters on its first exception rather than waiting out the
    server's three, so the spec that needs a ``failed`` run in the list
    gets one without a backoff in the middle of an a11y gate.
    """

    wf = Workflow("flop")

    @wf.node(start=True, retries=0)
    async def burst():
        raise RuntimeError(FLOP_ERROR)

    return wf


def _ladder() -> Workflow:
    """Eight nodes in a line, so the graph is eight ranks tall.

    Every node names the next one and returns it, which is the whole of
    it: nothing waits, nothing asks, nothing fans out. What the spec
    reads is the height — eight ranks is taller than a 320 px canvas can
    draw at the zoom the interaction floor allows, so this is the
    workflow that says whether the fit has a floor of its own.
    """

    wf = Workflow("ladder")

    @wf.node(start=True)
    async def intake(sort):
        return sort

    @wf.node()
    async def sort(weigh):
        return weigh

    @wf.node()
    async def weigh(mix):
        return mix

    @wf.node()
    async def mix(heat):
        return heat

    @wf.node()
    async def heat(cool):
        return cool

    @wf.node()
    async def cool(pack):
        return pack

    @wf.node()
    async def pack(label):
        return label

    @wf.node()
    async def label():
        return "labelled"

    return wf


def _plugged() -> Workflow:
    """A workflow that ships a web component, and a pane that mounts it.

    ``assets="./static"`` is resolved relative to *this module* (09
    §Escape hatch), so the directory beside this file is what the server
    serves at ``/plugins/plugged/static/`` and what the manifest lists.
    The panel names the tag ``static/playfield.js`` defines; nothing in
    the SPA knows that tag, which is what makes the pane a real test of
    the seam rather than of a builtin.
    """

    wf = Workflow("plugged", assets="./static")

    @wf.node(start=True)
    async def play():
        """One round, so the run reaches a terminal state promptly."""

        return {"word": PLAYFIELD_WORD}

    @wf.route("/state")
    async def state(ctx: PluginContext) -> dict:
        """What the element draws: the run it is scoped to, and a word."""

        return {
            "word": PLAYFIELD_WORD,
            "run_id": ctx.run_id,
            "title": ctx.run.title if ctx.run is not None else None,
        }

    wf.panel(
        "Playfield",
        slot="run",
        kind="custom",
        element="e2e-playfield",
        refresh_on=["log.appended"],
    )
    return wf


#: The six, built at import: ``athanore serve <file>:<attr>`` resolves
#: an attribute and refuses anything that is not a :class:`Workflow`
#: already (11 §Server), so a factory would never be reached.
probe = _probe()
spread = _spread()
hold = _hold()
flop = _flop()
ladder = _ladder()
plugged = _plugged()

"""`rps` — rock, paper, scissors, best of three. No agent, all engine.

A test workflow, and the cheapest possible exercise of the parts that are
hard to see working any other way: a `human_input` that opens a request,
parks the task and gives its worker slot back; a loop-back edge that the
engine walks as many times as the body asks it to; and a run that ends
with a real output. It costs nothing to run and answers in three clicks,
which is what you want from the thing you point a new crontab at.

**Nothing here is an agent**, so nothing here is uncertain. The machine's
throw is `random.choice`, the scoring is a table, and the routing is the
return value — rule 2 with no model anywhere near it. If a run of this
misbehaves, the engine is wrong; there is nothing else left.

**It is on its own pool.** `feature` runs on a capacity-1 `checkout` pool
because it mutates the working tree and two of it at once would be two
agents on one branch. This mutates nothing, so putting it there would
mean a game waiting on a person blocked the build — and a `human_input`
gives its slot back precisely so that waiting is free. Its own pool with
room for a few keeps those two facts from colliding
(:mod:`workflows.__main__`).

Play it::

    athanore submit rps "best of three"

or schedule it from the crontab pane, which is what it is for.
"""

from __future__ import annotations

import random
from typing import Any

from athanore import Workflow, current_task, human_input

__all__ = ["THROWS", "WINS", "decide", "wf"]

wf = Workflow("rps")

#: The three throws, in the order the request panel offers them.
THROWS: tuple[str, ...] = ("rock", "paper", "scissors")

#: What beats what: ``WINS[a] == b`` means ``a`` beats ``b``. A table
#: rather than modular arithmetic on an index, because the table is the
#: rules and arithmetic is a way of remembering them.
WINS: dict[str, str] = {"rock": "scissors", "paper": "rock", "scissors": "paper"}

#: Wins needed. Best of three is first to two, not three rounds played:
#: a third round after 2–0 decides nothing.
TARGET = 2


def decide(you: str, me: str) -> str:
    """``"you"``, ``"me"`` or ``"draw"`` for one round."""

    if you == me:
        return "draw"
    return "you" if WINS[you] == me else "me"


async def _log(text: str) -> None:
    await current_task().services.log.append(text)


@wf.node(start=True, retries=0, timeout=60)
async def kickoff(play, *, payload):
    """Set the scoreboard up. Deterministic, and over in a millisecond."""

    title = str(payload.get("title", "")).strip() or "best of three"
    await _log(f"kickoff: {title} — first to {TARGET} wins")
    return play({**payload, "you": 0, "me": 0, "round": 1, "history": []})


@wf.node(retries=0, timeout=None)
async def play(play, tally, *, payload):
    """One round: ask, throw, score, and either go again or stop.

    **The loop-back is the first parameter, and it is this node itself.**
    Rule 1 — the signature is the graph — so a node that can send work to
    itself declares itself as an edge, exactly as `feature`'s `gate`
    declares `implement`. The engine walks it as a fresh task each time,
    so every round is its own row with its own request, and a game
    abandoned half way is a run you can read rather than a body stuck in
    a `while` nobody can see into.

    `timeout=None` because the only thing this waits on is a person, and
    a node timeout is not the way to express "answer within a minute" —
    `human_input(timeout=…)` is, and this deliberately does not set one.
    """

    number = int(payload["round"])
    you = str(
        await human_input(
            f"round {number} — you {payload['you']}, me {payload['me']}. Throw:",
            options=list(THROWS),
        )
    )
    me = random.choice(THROWS)
    winner = decide(you, me)

    scores = {"you": int(payload["you"]), "me": int(payload["me"])}
    if winner != "draw":
        scores[winner] += 1
    line = f"round {number}: you {you}, me {me} — " + (
        "a draw, again" if winner == "draw" else f"{winner} take it"
    )
    await _log(line)

    history = [
        *payload["history"],
        {"round": number, "you": you, "me": me, "winner": winner},
    ]
    state: dict[str, Any] = {
        **payload,
        **scores,
        "round": number + 1,
        "history": history,
    }
    if max(scores.values()) >= TARGET:
        return tally(state)
    return play(state)


@wf.node(retries=0, timeout=60)
async def tally(*, payload):
    """Terminal: who won, and the whole game as a list of rounds."""

    you, me = int(payload["you"]), int(payload["me"])
    winner = "you" if you > me else "me"
    await _log(f"tally: {you}–{me}, {winner} win")
    return {
        "winner": winner,
        "score": {"you": you, "me": me},
        "rounds": payload["history"],
    }

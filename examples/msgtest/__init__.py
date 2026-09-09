"""msgtest — exercises the human-in-the-loop message channel.

Three nodes, two questions, **zero agents**: the whole workflow is asking
the operator things and threading the answers forward.

    ask → confirm → wrap

It is the cheapest way to try the requests API, the CLI's ``requests`` /
``answer`` verbs, and the SPA's inbox and request cards, because nothing
in it spends any inference — which is also why it is what the end-to-end
suites drive. A workflow with an agent in it cannot be run by a person
who only wants to see whether a question arrives.

**The two questions are two of 06's three modes**, deliberately: the
first is free text and the second is a choice, so one run renders both a
text field and a set of options, in the CLI and in the browser. The third
mode — a form from a pydantic model — belongs to a workflow that has one
to ask for; adding a fourth node to reach it would make this the thing it
exists not to be.

**Waiting does not hold a worker.** Each ``human_input`` releases the
attempt's pool slot for the duration of the wait and takes one back
through the pool's re-admit queue when the answer arrives (04 §Waiting),
so a run parked on question 1 does not stop the rest of the server. That
is the property this workflow is the easiest way to watch.

Serve it with ``athanore serve`` (it is an entry point of the
``athanore-examples`` distribution) or with ``python -m examples``::

    athanore submit msgtest "test run"
    athanore requests <run>                # what is waiting
    athanore answer <req> athanor          # question 1, the text typed
    athanore answer <req> approve          # question 2, an option id

...or from the SPA's inbox.
"""

from __future__ import annotations

from typing import Any

from athanore import Workflow, current_task, human_input

__all__ = ["APPROVE", "OPTIONS", "QUESTION_ONE", "QUESTION_TWO", "REJECT", "wf"]

#: The first question: free text, so the answer is whatever was typed.
QUESTION_ONE = "Messaging test, question 1/2: what should the secret word be?"

#: The second, as a template over the first answer: a choice, so the
#: answer is one of :data:`OPTIONS` and the surfaces render buttons.
QUESTION_TWO = "Messaging test, question 2/2: the secret word is '{word}'.\nApprove it?"

APPROVE = "approve"
REJECT = "reject"

#: What question 2 offers. Ids rather than mappings, because a two-option
#: choice needs no names and no kinds (06 §The model), and the id is what
#: comes back.
OPTIONS = [APPROVE, REJECT]

wf = Workflow("msgtest")


@wf.node(start=True, retries=0)
async def ask(confirm):
    """Ask for the word, and carry the answer to the next node.

    ``retries=0`` on all three nodes: the only way a body that just asks
    a question fails is that the wait was given up on, and asking the
    operator the same question again is not a retry policy. (A *crash* is
    a different thing and is not a retry — a re-executed attempt
    re-attaches to the request it already opened, by ordinal, and is
    handed the answer that is already there; 06 §Restart durability.)
    """

    return confirm(await human_input(QUESTION_ONE))


@wf.node(retries=0)
async def confirm(wrap, *, word):
    """Show the word back and ask for a verdict, as a choice."""

    verdict = await human_input(QUESTION_TWO.format(word=word), options=OPTIONS)
    return wrap({"word": word, "verdict": verdict})


@wf.node(retries=0)
async def wrap(*, answers):
    """Record both answers and end the run with them.

    No edges, so this is the terminal node and what it returns is the
    run's output (04 §Routing interpretation) — the same pair the work
    log carries, so a client that reads either sees the same thing.
    """

    word = _answer(answers, "word")
    verdict = _answer(answers, "verdict")
    await current_task().services.log.append(
        f"secret word: {word}; operator verdict: {verdict}",
        author="engine",
        kind="deliverable",
    )
    return {"word": word, "verdict": verdict}


def _answer(answers: Any, key: str) -> str:
    """One answer of the pair, whatever shape the payload arrived in.

    Payloads are coerced with ``jsonable()`` (04 §Routing interpretation),
    and an operator who moved a task onto this node by hand may have sent
    something else entirely. An answer nobody gave is the empty string
    rather than a ``KeyError``: this node's job is to record what there
    is.
    """

    return str(answers.get(key, "")) if isinstance(answers, dict) else ""

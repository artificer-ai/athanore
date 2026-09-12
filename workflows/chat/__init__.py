"""`chat` — one agent, one operator, turn after turn until you say stop.

The smallest workflow with a model in it. Every turn is the same three
things: a `human_input` that opens a text request and parks the task
(its slot given back — a chat idles for hours and holds nothing while it
does), one agent run on what you typed, and a loop-back edge to itself.
Say `/quit` and it lands on `wrap`, which returns the transcript as the
run's output.

**Each turn is a fresh ACP session.** The adapter has no resume seam
yet, so the agent's memory is the conversation carried in the payload
and handed back to it in the assignment, last :data:`MEMORY` turns of
it. That is honest rather than clever: a resumed session would make
this cheaper and the model sharper, and when `ACPAgent` grows one the
change here is one attribute.

**The agent is the sandbox's.** `./scripts/agent.sh <pi|claude>` in the
dev container, like `feature`'s seats, so `auto_allow` is safe for the
same reason it is there (05 §User-land adapters, D75). Elicitations are
*asked* rather than declined, because unlike a build there is a person
at the other end of this one.

**The pane is the chat.** A `run`-slot custom panel, `<athanore-chat>`
in `static/chat.js`, draws the conversation from the work log and puts a
composer under it. Sending answers the turn's open request, which is all
a message ever is here — so the request pane, the CLI and this pane are
three views of one channel, and nothing is lost by using any of them.
The plugin's three routes are the pane's data, its send, and the
reply in progress; all are run-scoped (`?run_id=`), so the pane shows
this run's chat and no other.

**The reply streams.** While the agent is answering, the pane follows
the ephemeral `task.stream` event (08 §Tasks) and pulls the turn's
`text` chunks through `draft`, so what the model is typing shows up as
a draft bubble before the turn's `reply` lands in the work log. The
bridge binds a pane's `fetch` to the plugin's own prefix (09 §Escape
hatch), which is why `draft` exists rather than the pane reading
`/api/tasks/{id}/stream` itself.

Talk to it::

    athanore submit chat "hello"

then select the run and cycle to its `chat` pane.
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import Request
from pydantic import BaseModel, Field

from athanore import (
    ACPAgent,
    PluginContext,
    PluginError,
    Workflow,
    current_task,
    human_input,
)
from athanore.store.rows import ChunkKind, TaskStatus
from workflows.feature.sandbox import AGENT_SH, CHECKOUT

__all__ = ["AGENT", "MEMORY", "STOP_WORDS", "ChatAgent", "Reply", "Say", "wf"]

wf = Workflow("chat", assets="./static")

#: Which adapter answers: `pi` (the blank slate) or `claude`.
AGENT = os.environ.get("CHAT_AGENT", "pi")
#: The model, resolved by category from what the session advertises (05
#: §Agent classes); unset leaves the adapter's own default.
MODEL = os.environ.get("CHAT_MODEL") or None
#: How long one reply may take. A chat turn, not a build.
TURN_TIMEOUT = float(os.environ.get("CHAT_TURN_TIMEOUT", 600))
#: How many earlier turns the agent is reminded of. Every turn re-sends
#: them, so this is the prompt's size as much as the agent's memory.
MEMORY = int(os.environ.get("CHAT_MEMORY", 20))

#: What ends the conversation, case-insensitively.
STOP_WORDS = frozenset({"/quit", "/exit", "/bye", "quit", "exit", "bye"})


class Reply(BaseModel):
    """What one turn submits. The reply is the *value*; everything else
    the agent printed — its banner, its reasoning, its sign-off — is
    transcript, and stays there. Without this, `AgentResult.text` would
    be the whole session's output, which is the wrong thing to show the
    operator and the wrong thing to hand the next turn as memory."""

    reply: str = Field(min_length=1, description="What you say back, verbatim.")


class ChatAgent(ACPAgent):
    """One reply, in the dev container, on this checkout."""

    command = [str(AGENT_SH), AGENT]
    cwd = str(CHECKOUT)
    model = MODEL
    permission_policy = "auto_allow"
    elicitation_policy = "ask"
    timeout = TURN_TIMEOUT
    output_model = Reply

    system_prompt = """# Chat

You are talking with the operator of this checkout, one message at a time.
Each message reaches you in a fresh session; the conversation so far is in
your assignment, and it is all the memory you have. Answer the last thing
they said, briefly. You may read and run things in the checkout if the
question needs it. Your reply is the `reply` you submit — submit it and
stop; do not also write it to the work log.
"""


async def _log(text: str) -> None:
    await current_task().services.log.append(text)


def _assignment(history: list[dict[str, str]], said: str) -> str:
    """The agent's prompt for this turn: recent history, then the message."""

    recent = history[-MEMORY:]
    if not recent:
        return said
    lines = ["Conversation so far, oldest first:"]
    for turn in recent:
        lines += [f"operator: {turn['you']}", f"you: {turn['agent']}"]
    lines += ["", "operator, now:", said]
    return "\n".join(lines)


def _ask(history: list[dict[str, str]]) -> str:
    """The request's prompt: the agent's last reply, then the cursor.

    The request panel is the chat turn — what was just said is above the
    box you type into — so the reply goes in the *prompt* rather than
    only in the work log, where it would be a pane away.
    """

    if not history:
        return "you:"
    return f"{AGENT}: {history[-1]['agent']}\n\nyou:"


@wf.node(start=True, retries=0, timeout=60)
async def kickoff(turn, *, payload):
    """Open the conversation. The title is the first thing said, if any."""

    opener = str(payload.get("title", "")).strip()
    await _log(f"kickoff: {AGENT} is listening — say /quit to end")
    return turn({**payload, "history": [], "opener": opener})


@wf.node(retries=0, timeout=None)
async def turn(turn, wrap, *, payload):
    """One exchange: ask, answer, and go again.

    The loop-back is the first parameter, as in `rps`: every turn is its
    own task with its own request, so a conversation abandoned half way
    is a run you can read. `timeout=None` because the only wait here is
    on a person; the agent's own ``timeout`` bounds the reply.

    A turn whose agent run *failed* — refused, cancelled, truncated — is
    logged as such and the conversation continues: `AgentResult.ok` is a
    fact to show the operator, not an exception, and they decide what to
    do with it. A run that raised is rule 3 as usual and fails the task.
    """

    history: list[dict[str, str]] = list(payload["history"])
    opener = str(payload.get("opener", ""))
    said = opener or str(await human_input(_ask(history))).strip()

    if said.lower() in STOP_WORDS:
        return wrap({**payload, "history": history, "opener": ""})
    if not said:
        await _log("(nothing said — say /quit to end)")
        return turn({**payload, "history": history, "opener": ""})

    await _log(f"you: {said}")
    result = await ChatAgent().run(_assignment(history, said))
    if result.ok:
        reply = result.output.reply.strip()
        await _log(f"{AGENT}: {reply}")
    else:
        reply = f"(turn {result.error})"
        await _log(f"{AGENT}: {reply}")

    history.append({"you": said, "agent": reply})
    state: dict[str, Any] = {**payload, "history": history, "opener": ""}
    return turn(state)


@wf.node(retries=0, timeout=60)
async def wrap(*, payload):
    """Terminal: the transcript."""

    history = payload["history"]
    await _log(f"wrap: {len(history)} turns")
    return {"agent": AGENT, "turns": len(history), "history": history}


# --- the pane -----------------------------------------------------------

#: The work-log prefixes the body writes and the pane reads back. One
#: place, so the two cannot disagree.
YOU = "you: "
THEM = f"{AGENT}: "


class Say(BaseModel):
    """One message from the composer."""

    text: str = Field(min_length=1)


async def _pending(request: Request, run_id: str) -> Any:
    """The run's open request, or ``None`` while the agent is answering.

    Read through the store the application holds rather than a plugin
    service, because 09's `services.requests` is the *attempt's* view —
    open, wait — and has no operator-side "which is pending" or
    "answer". This route is that operator, so it reaches the same two
    objects `/api/requests` does (`app.state.store`, `app.state.engine`).
    A plugin runs as the server's own Python (09 §Security), so this is a
    reach past the sugar, not past the trust model.
    """

    store = request.app.state.store
    if store is None:
        return None
    async with store.reader() as reader:
        views = await reader.requests.list_views(run_id, pending_only=True)
    return views[-1] if views else None


async def _view(ctx: PluginContext, request: Request) -> dict[str, Any]:
    assert ctx.run_id is not None
    run = await ctx.services.run.get()
    turns: list[dict[str, Any]] = []
    for entry in await ctx.services.run.log_entries():
        if entry.text.startswith(YOU):
            turns.append(
                {"who": "you", "text": entry.text[len(YOU) :], "ts": entry.created}
            )
        elif entry.text.startswith(THEM):
            turns.append(
                {"who": AGENT, "text": entry.text[len(THEM) :], "ts": entry.created}
            )
    pending = await _pending(request, ctx.run_id)
    return {
        "run": {"id": run.id, "title": run.title, "status": run.status},
        "agent": AGENT,
        "turns": turns,
        "pending": None if pending is None else {"id": pending.id},
    }


@wf.route("/turns")
async def turns(ctx: PluginContext, request: Request) -> dict[str, Any]:
    """The conversation so far, and whether it is the operator's turn."""

    return await _view(ctx, request)


async def _answering(request: Request, run_id: str) -> Any:
    """The run's ``in_progress`` task, or ``None`` when nothing is running.

    Every turn is its own task, and it is ``waiting`` while the question
    is open and ``in_progress`` while the agent answers it, so the one
    live task is the turn being answered and its transcript is that
    reply as it is typed. Read through the store for the same reason
    :func:`_pending` is.
    """

    store = request.app.state.store
    if store is None:
        return None
    async with store.reader() as reader:
        tasks = await reader.tasks.list_for_run(run_id)
    live = [task for task in tasks if task.status == TaskStatus.in_progress]
    return max(live, key=lambda task: task.id) if live else None


@wf.route("/draft")
async def draft(ctx: PluginContext, request: Request, after: int = 0) -> dict[str, Any]:
    """The reply being typed: the live turn's ``text`` chunks after ``after``.

    ``task_id`` is ``None`` when no turn is being answered. The pane
    passes the ``last_seq`` it saw and appends what comes back, the same
    cursor ``/api/tasks/{id}/stream`` pages by; ``last_seq`` counts every
    chunk kind, so a page of only tool calls still moves the cursor.
    """

    assert ctx.run_id is not None
    task = await _answering(request, ctx.run_id)
    if task is None:
        return {"task_id": None, "chunks": [], "last_seq": 0}
    store = request.app.state.store
    async with store.reader() as reader:
        chunks = await reader.stream.list_after(task.id, after)
        last_seq = await reader.stream.last_seq(task.id)
    return {
        "task_id": task.id,
        "chunks": [
            {"seq": chunk.seq, "text": chunk.text}
            for chunk in chunks
            if chunk.kind == ChunkKind.text
        ],
        "last_seq": last_seq,
    }


@wf.route("/say", methods="POST")
async def say(ctx: PluginContext, request: Request, body: Say) -> dict[str, Any]:
    """Send one message: answer the turn's open request with it."""

    assert ctx.run_id is not None
    pending = await _pending(request, ctx.run_id)
    if pending is None:
        raise PluginError(409, f"not your turn — {AGENT} is answering")
    engine = request.app.state.engine
    if engine is None or engine.requests is None:
        raise PluginError(503, "this server has no request service")
    await engine.requests.answer(pending.id, value=body.text)
    return await _view(ctx, request)


wf.panel("chat", slot="run", kind="custom", element="athanore-chat")

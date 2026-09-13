"""`chat` — one agent, one operator, one session, turn after turn until you say stop.

The smallest workflow with a model in it, and the proof 23 §Why asks
for. One node, `talk`, opens the agent once with `open()` and holds it
for the length of the conversation. Every turn is a `human_input` that
opens a text request and parks the task with its slot given back (a
chat idles for hours and holds nothing while it does), then one
`prompt()` on the same session. Say `/quit` and `talk` returns the
transcript as the run's output.

**The agent's memory is its own.** The prompt is the message; the
session has the rest. Nothing is pasted back, so a turn costs a turn.
The session id is the one thing the body writes down — a `session <id>`
line in the work log, author `engine` — because a server restart
re-executes the attempt from its first line (D6), replays the answered
questions (06 §Restart durability), and the body then re-opens *that*
session (`continuing session` in the new transcript, 05 §Continuing a
session) rather than a blank one; a rerun does the same from the run's
log. A session that cannot be continued is a refusal, not a fresh start
(23 §Refusal).

**The agent is the sandbox's.** `./scripts/agent.sh <pi|claude>` in the
dev container, like `feature`'s seats, so `auto_allow` is safe for the
same reason it is there (05 §User-land adapters, D75). Elicitations are
*asked* rather than declined, because unlike a build there is a person
at the other end of this one.

**The pane is the chat.** A `run`-slot custom panel, `<athanore-chat>`
in `static/chat.js`, draws the conversation from the work log and puts a
composer under it. Sending answers the run's open request, which is all
a message ever is here — so the request pane, the CLI and this pane are
three views of one channel, and nothing is lost by using any of them.
The plugin's three routes are the pane's data, its send, and the
reply in progress; all are run-scoped (`?run_id=`), so the pane shows
this run's chat and no other. The pool slot (`talk`, capacity 2) counts
replies being generated, not chats open: a parked conversation holds
nothing (23 §What the pool slot means).

**The reply streams.** While the agent is answering, the pane follows
the ephemeral `task.stream` event (08 §Tasks) and pulls the turn's
`text` chunks through `draft`, so what the model is typing shows up as
a draft bubble before the turn's `reply` lands in the work log. One
task carries every reply of the chat, so the body marks each turn's
start in the transcript with a `you:` notice and `draft` pages from the
last one. The bridge binds a pane's `fetch` to the plugin's own prefix
(09 §Escape hatch), which is why `draft` exists rather than the pane
reading `/api/tasks/{id}/stream` itself.

Talk to it::

    athanore submit chat "hello"

then select the run and cycle to its `chat` pane.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import Request
from pydantic import BaseModel, Field

from athanore import (
    ACPAgent,
    AgentSession,
    PluginContext,
    PluginError,
    Workflow,
    current_task,
    human_input,
)
from athanore.store.rows import ChunkKind, TaskStatus
from workflows.feature.sandbox import AGENT_SH, CHECKOUT

__all__ = ["AGENT", "STOP_WORDS", "ChatAgent", "Say", "wf"]

wf = Workflow("chat", assets="./static")

#: Which adapter answers: `pi` (the blank slate) or `claude`.
AGENT = os.environ.get("CHAT_AGENT", "pi")
#: The model, resolved by category from what the session advertises (05
#: §Agent classes); unset leaves the adapter's own default.
MODEL = os.environ.get("CHAT_MODEL") or None
#: How long the handshake, and then one reply, may take. A chat turn,
#: not a build.
TURN_TIMEOUT = float(os.environ.get("CHAT_TURN_TIMEOUT", 600))

#: What ends the conversation, case-insensitively.
STOP_WORDS = frozenset({"/quit", "/exit", "/bye", "quit", "exit", "bye"})

#: The work-log prefixes the body writes and the pane reads back. One
#: place, so the two cannot disagree.
YOU = "you: "
THEM = f"{AGENT}: "

#: The work-log line that names the session, author `engine`, so a
#: re-executed attempt finds it: the last such line in the run's log.
SESSION = "session "


class ChatAgent(ACPAgent):
    """The one agent of a conversation, in the dev container, on this checkout.

    ``cwd`` and ``timeout`` are given at construction (05 §Agent classes):
    the checkout, so the session's ``cwd`` is the same on every re-open,
    and one reply's budget, which bounds the handshake and then each
    prompt — never the block, which idles for hours.
    """

    command = [str(AGENT_SH), AGENT]
    model = MODEL
    permission_policy = "auto_allow"
    elicitation_policy = "ask"

    system_prompt = """# Chat

You are talking with the operator of this checkout, one message at a time,
in one session that lasts the whole conversation: what was said before is
your own memory, and each message you receive is the next thing they said.
Answer it, briefly, in plain text. You may read and run things in the
checkout if the question needs it.

There is no task here for you to finish and nothing for you to submit.
The conversation ends only when the operator ends it, never on your own
account: keep answering, one message at a time, until they do. Do not
write your answer to the work log — say it in your reply, and it is
recorded for you.
"""


async def _log(text: str) -> None:
    await current_task().services.log.append(text)


def _ask(history: list[dict[str, str]]) -> str:
    """The request's prompt: the agent's last reply, then the cursor.

    The request panel is the chat turn — what was just said is above the
    box you type into — so the reply goes in the *prompt* rather than
    only in the work log, where it would be a pane away.
    """

    if not history:
        return "you:"
    return f"{AGENT}: {history[-1]['agent']}\n\nyou:"


@dataclass(frozen=True)
class Recorded:
    """What the run's work log says before this execution adds to it."""

    #: The session the run's last `session <id>` line names, or None.
    session_id: str | None
    #: This task's `you:` lines, in order — the messages it has logged.
    said: list[str]
    #: This task's reply lines, in order — the messages it has answered.
    replies: list[str]


async def _recorded() -> Recorded:
    """Read the run's work log the way this task's agent would.

    A body can append to its work log and cannot read it back
    (``TaskServices.log`` is ``append``; 04 §TaskContext), so the read is
    the one every agent has: ``GET /api/agent/tasks/{id}`` with the task
    token (05 §Tooling tiers), which returns the whole run's log less its
    ``stats`` lines. Two things are read from it. The session to
    continue is the run's — its last ``session <id>`` line, from any
    attempt, so a rerun carries the conversation on. The turns already
    answered are **this task's** — the ``you:`` and reply lines with
    this ``task_id`` — because they are what a re-executed attempt's
    replayed ``human_input`` answers correspond to (06 §Restart
    durability); a rerun is a new task row whose answers are new.

    A read that fails raises: a body that cannot read the run's log
    cannot know whether it is continuing a conversation, and quietly
    starting over is the failure 23 §Refusal exists to remove.
    """

    ctx = current_task()
    async with httpx.AsyncClient(base_url=ctx.api_base, timeout=10.0) as http:
        response = await http.get(
            f"/api/agent/tasks/{ctx.task_id}",
            headers={"X-Athanore-Token": ctx.token},
        )
        response.raise_for_status()
    entries: list[dict[str, Any]] = response.json()["log"]
    session_id: str | None = None
    said: list[str] = []
    replies: list[str] = []
    for entry in entries:
        text: str = entry["text"]
        if entry["author"] == "engine" and text.startswith(SESSION):
            session_id = text[len(SESSION) :].strip() or None
        elif entry["task_id"] != ctx.task_id:
            continue
        elif text.startswith(YOU):
            said.append(text[len(YOU) :])
        elif text.startswith(THEM):
            replies.append(text[len(THEM) :])
    return Recorded(session_id, said, replies)


async def _reply(session: AgentSession, said: str) -> str:
    """Ask the held session one thing and log what came back.

    Before the prompt, one ``notice`` chunk — ``you: <said>`` — goes to
    the transcript and is flushed: the reply's start, which is what
    ``draft`` pages from (one task carries every reply of the chat), and
    a line a reader of the transcript sees between one reply and the
    next. ``notice`` because it is the kind that is not the model's (03
    §StreamChunk). The reply itself is the agent's text; a failed turn's
    reply is its error, in parentheses.
    """

    services = current_task().services
    await services.stream.append(ChunkKind.notice, f"{YOU}{said}")
    await services.stream.flush()
    result = await session.prompt(said)
    if result.ok:
        reply = result.text.strip()
    else:
        reply = f"(turn {result.error})"
    await _log(f"{THEM}{reply}")
    return reply


@wf.node(start=True, retries=0, timeout=None)
async def talk(*, payload):
    """The whole conversation: one agent, opened once, asked turn after turn.

    The block is the conversation (05 §Holding a session). Its entry
    spawns the agent and opens the session — or re-opens the one the
    work log names, when this attempt is re-executed after a crash or
    the run is rerun — and each turn is a ``human_input``, which parks
    the task with its slot given back (04 §Waiting), then one
    ``prompt()`` on the held session. ``timeout=None`` because the only
    wait here is on a person; the agent's own ``timeout`` bounds each
    reply. ``retries=0`` because a conversation is not retried: an
    attempt that dies is re-executed as itself (D6) and picks the
    session back up.

    Re-execution replays the answered questions at once (06 §Restart
    durability), so the loop counts the messages it sees against the
    ones this task already answered and skips those: the log has both
    lines, and the agent — the same session — already heard them. A
    message whose ``you:`` line landed but whose reply did not is asked
    again without a second ``you:`` line.

    A reply that *failed* — refused, cancelled, truncated — is logged as
    such and the conversation continues: ``AgentResult.ok`` is a fact to
    show the operator, not an exception, and the session is still open.
    A prompt that raised (a transport failure, a timeout) is rule 3 as
    usual: the session is dead and so is the task, and a rerun continues
    the session from its work log.
    """

    opener = str(payload.get("title", "")).strip()
    recorded = await _recorded()
    history = [
        {"you": you, "agent": reply}
        for you, reply in zip(recorded.said, recorded.replies, strict=False)
    ]
    agent = ChatAgent(
        cwd=str(CHECKOUT), timeout=TURN_TIMEOUT, session_id=recorded.session_id
    )
    async with agent.open() as session:
        await current_task().services.log.append(
            f"{SESSION}{session.session_id}", author="engine"
        )
        seen = 0
        first = True
        while True:
            if first and opener:
                said = opener
            else:
                said = str(await human_input(_ask(history))).strip()
            first = False
            if said.lower() in STOP_WORDS:
                break
            if not said:
                continue
            seen += 1
            if seen <= len(recorded.replies):
                continue  # answered before this execution: both lines are logged
            if seen > len(recorded.said):
                await _log(f"{YOU}{said}")
            reply = await _reply(session, said)
            history.append({"you": said, "agent": reply})
    return {
        "agent": AGENT,
        "session_id": session.session_id,
        "turns": len(history),
        "history": history,
    }


# --- the pane -----------------------------------------------------------


class Say(BaseModel):
    """One message from the composer."""

    text: str = Field(min_length=1)


async def _pending(request: Request, run_id: str) -> Any:
    """The run's open request, or ``None`` while the agent is answering.

    One task, so at most one: the turn's ``human_input`` while it is the
    operator's turn, or an elicitation the agent raised mid-reply
    (``elicitation_policy="ask"``). If the agent ever has two open at
    once, the oldest is the one to answer first.

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
    return views[0] if views else None


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

    The conversation is one task: ``waiting`` while a question is open,
    ``in_progress`` while the agent answers it, so the answering task is
    the one task when it is answering. More than one ``in_progress``
    task in a run of a one-node workflow is a state the engine cannot
    produce, and is refused rather than picked from. Read through the
    store for the same reason :func:`_pending` is.
    """

    store = request.app.state.store
    if store is None:
        return None
    async with store.reader() as reader:
        tasks = await reader.tasks.list_for_run(run_id)
    live = [task for task in tasks if task.status == TaskStatus.in_progress]
    if len(live) > 1:
        raise PluginError(500, f"run {run_id} has {len(live)} tasks answering at once")
    return live[0] if live else None


@wf.route("/draft")
async def draft(ctx: PluginContext, request: Request, after: int = 0) -> dict[str, Any]:
    """The reply being typed: the live turn's ``text`` chunks after ``after``.

    ``task_id`` is ``None`` when no turn is being answered. The pane
    passes the ``last_seq`` it saw and appends what comes back, the same
    cursor ``/api/tasks/{id}/stream`` pages by; ``last_seq`` counts every
    chunk kind, so a page of only tool calls still moves the cursor. One
    task carries every reply of the chat, so a page that contains a turn
    marker is cut to what follows the last one: the reply being typed,
    not the conversation before it.
    """

    assert ctx.run_id is not None
    task = await _answering(request, ctx.run_id)
    if task is None:
        return {"task_id": None, "chunks": [], "last_seq": 0}
    store = request.app.state.store
    async with store.reader() as reader:
        chunks = await reader.stream.list_after(task.id, after)
        last_seq = await reader.stream.last_seq(task.id)
    # One task carries every reply of the chat, and the pane restarts
    # its cursor at 0 on each turn: the reply being typed is what follows
    # the turn's own marker, the `you:` notice the body wrote before it.
    for index in range(len(chunks) - 1, -1, -1):
        chunk = chunks[index]
        if chunk.kind == ChunkKind.notice and chunk.text.startswith(YOU):
            chunks = chunks[index + 1 :]
            break
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
    """Send one message: answer the run's open request with it."""

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

# T091 — `chat` as one held session

**Task.** `docs/v1/17-serial-task-plan.md` § `### T091`.
**Specs.** `docs/v1/23-session-continuity.md` §Why (the seat is the
proof this document asks for), §A session held open — §Surface (the
loop this seat is the example of), §Lifecycle of a held session (step 2:
the node's `timeout` is the bound on the block and is paused while
`waiting`; step 6: after a crash the block is entered again, the
answered `human_input`s replay, and the session is a fresh one unless
the body hands back the `session_id` it wrote down), §What the pool
slot means (`talk`, capacity 2, is two replies at once), §Stats of a
held session (one `[stats]` line per reply, one `session=` on all of
them), §Testing (the seat is not tested by the gate); `docs/v1/05-
agents.md` §Agent classes (`cwd`, `timeout` and `session_id` are
arguments of construction), §Holding a session, §Continuing a session
(the `continuing session <id>` notice, the refusal with no fallback),
§Tooling tiers (the task block: `GET {api_base}/api/agent/tasks/N`
reads "title, description, FULL work log" with the task token);
`docs/v1/04-engine.md` §TaskContext (`TaskServices` is
`log.append`, `stream.append`, `submissions.latest()`, `requests.*`,
`run.get()`, `stats.record` — there is no log *read* for a body),
§Waiting (the slot given back while parked); `docs/v1/06-requests.md`
§Restart durability (answers replay by ordinal on the same task row; a
retry or rerun is a new row and asks afresh); `docs/v1/08-api.md`
§Agent-facing (`/api/agent/tasks/{id}` returns the run's log less its
`stats` entries, D56); `docs/v1/18-event-payloads.md` (`task.stream`,
`log.appended`); `docs/v1/09-
plugins.md` §Escape hatch (why `draft` exists); `docs/v1/03-domain-
model.md` §LogEntry and §StreamChunk (`notice` is the one kind that is
not the model's); D264 (the decision this seat is the proof of), D266
(what T090 settled), D6 (re-execute from the first line), D56.

This plan was written against the code as of `0a9b61e` (T090 merged).
`workflows/chat/__init__.py` (341 lines) is three nodes — `kickoff`
(start), `turn` (loop-back to itself, `wrap` on a stop word) and `wrap`
(terminal) — with `MEMORY`, `_assignment` (the last `MEMORY` turns
pasted into the prompt), `_ask` (the request's prompt: the last reply,
then `you:`), `_log`, `ChatAgent` (`command`, `cwd`, `model`,
`permission_policy="auto_allow"`, `elicitation_policy="ask"`,
`timeout`, `output_model=Reply`, `system_prompt` saying "each message
reaches you in a fresh session; the conversation so far is in your
assignment"), `Reply`, `Say`, `YOU`/`THEM`, the pane's three routes
(`turns` → `_view`, `draft` → `_answering`, `say` → `_pending`) and the
panel declaration. `_pending` returns `views[-1]` of the run's pending
requests; `_answering` returns the newest `in_progress` task of the
run. `static/chat.js` reads `turns` (parsed from the work log by the
`YOU`/`THEM` prefixes), `pending`, and pulls `draft?after=<seq>` on
every `task.stream`; on a `task_id` change it restarts its cursor at 0,
and **on every turn of yours it resets its draft to `{taskId: null,
seq: 0, text: ''}`**. `workflows/__main__.py` registers `chat` on
`Pool("talk", capacity=2)`. `ACPAgent.open()` (T090) yields an
`AgentSession` with `session_id` and `prompt()`; `ACPAgent.__init__`
sets `self.cwd = cwd` and `self.timeout = timeout` **unconditionally**,
so a class-level `cwd` or `timeout` on a subclass is shadowed by `None`
on every instance (05 §Agent classes lists both as constructor
arguments, not class attributes; `ChatAgent` has both as class
attributes today and neither takes effect). A body reaches its work
log only by writing: `TaskServices.log` is `append`, `TaskServices.run`
is `get`; the reads (`reader.log.list`, `PluginRuns.log_entries`) are
the store's and the plugin context's, neither of which a body holds.
The agent-facing `GET /api/agent/tasks/{id}` (`athanore/api/routers/
agent.py`) returns `AgentTask.log`, the whole run's entries less
`stats`, each a `LogEntry` with `id`, `task_id`, `node`, `author`,
`kind`, `text`; it is authenticated by `X-Athanore-Token` against the
engine's live registry, in which the attempt is registered for the
whole of its body (04 §TaskContext). `TaskContext` carries `api_base`
(`settings.public_url`) and `token`. `StreamService` (`services.
stream`) has `append(kind, text) -> seq` and `flush()`, and the
transcript's `seq` continues across a re-execution of the same task
row (the counter resolves from the store's `last_seq`).

## What this task is

`workflows/chat/__init__.py` becomes one node, `talk`, that opens
`ChatAgent` once with `open()` — continuing the session the run's work
log names, when it names one — writes `session <id>` to the work log as
an `engine` line, and loops `human_input` and `prompt()` on that one
session until a stop word, when it returns the transcript. `kickoff`,
`turn`, `wrap`, `MEMORY` and `_assignment` go; the system prompt stops
saying the conversation is in the prompt; the module docstring says
what the seat now is. `_pending` and `_answering` find the run's one
open request and one answering task rather than the newest of many.
The pane's file is byte-identical, `workflows/__main__.py` is untouched,
and nothing on the wire changes.

Three things the task entry does not spell out, settled here by reading
the code, and recorded as D267 (§Documents):

1. **How the body reads the work log.** Over its own task API — `GET
   {api_base}/api/agent/tasks/{task_id}` with `X-Athanore-Token` — the
   read 05 §Tooling tiers gives every agent and the only read of the
   log a body has. Adding a read to `TaskServices` would be a change to
   04 and the engine, which the task does not name.
2. **What a re-executed attempt does with its replayed answers.** 06
   §Restart durability replays every answered `human_input` at once;
   without reconciliation the body would re-log and re-prompt each one
   on the continued session. The same log read tells the body which of
   this task's messages already have a reply, and it skips those.
3. **How `draft` finds the reply being typed.** One task now carries
   every reply's chunks, and the pane restarts its cursor at 0 on every
   turn, so `draft?after=0` would replay the whole conversation as a
   draft bubble. The body writes one `notice` chunk, `you: <message>`,
   to the transcript before each prompt (`stream.append` is a body
   service, 04 §TaskContext) and `draft` pages from the last such
   marker. The pane needs no change for it and its response shape is
   the same.

Files touched, and nothing else: `workflows/chat/__init__.py`,
`docs/v1/17-serial-task-plan.md` (the `**Status.** Done.` line),
`docs/v1/15-decisions.md` (D267), `docs/v1/23-session-continuity.md`
(one sentence of §Why, below). **Not** `workflows/chat/static/chat.js`,
not `workflows/__main__.py`, not `athanore/`, not `tests/`, not
`tests/snapshots/openapi.json` or `web/src/api/gen/` — `git diff
--exit-code` on the last two is part of verification.

## The seat (`workflows/chat/__init__.py`)

### 1. What stays

Unchanged, character for character unless named below: the imports
except as §8 says; `wf = Workflow("chat", assets="./static")`; `AGENT`,
`MODEL`, `TURN_TIMEOUT` (its comment aside, §3), `STOP_WORDS`; `Reply`; `_log`; `_ask`; `YOU`,
`THEM`; `Say`; `_view`; the `turns` and `say` routes; the `draft`
route's signature and docstring shape; `wf.panel("chat", slot="run",
kind="custom", element="athanore-chat")`.

`__all__` loses `"MEMORY"`: `["AGENT", "STOP_WORDS", "ChatAgent",
"Reply", "Say", "wf"]`.

### 2. What goes

`MEMORY` (and its `CHAT_MEMORY` environment variable), `_assignment`,
`kickoff`, `turn`, `wrap`. Nothing else in the repository names any of
them (`grep -rn "CHAT_MEMORY\|MEMORY\b" --include=*.py --include=*.md
--include=*.example .` finds only this module and `docs/v1/23` §Why,
which §Documents amends).

### 3. `ChatAgent`

```python
class ChatAgent(ACPAgent):
    """The one agent of a conversation, in the dev container, on this checkout.

    ``cwd`` and ``timeout`` are given at construction (05 §Agent classes):
    the checkout, so the session's ``cwd`` is the same on every re-open,
    and one reply's budget, which bounds the handshake and then each
    prompt with its repairs — never the block, which idles for hours.
    """

    command = [str(AGENT_SH), AGENT]
    model = MODEL
    permission_policy = "auto_allow"
    elicitation_policy = "ask"
    output_model = Reply

    system_prompt = """# Chat

You are talking with the operator of this checkout, one message at a time,
in one session that lasts the whole conversation: what was said before is
your own memory, and each message you receive is the next thing they said.
Answer it, briefly. You may read and run things in the checkout if the
question needs it. Your reply is the `reply` you submit — submit it and
stop; do not also write it to the work log.
"""
```

The class attributes `cwd` and `timeout` are removed because
`ACPAgent.__init__` overwrites both on every instance (§This plan was
written against); `talk` passes them: `ChatAgent(cwd=str(CHECKOUT),
timeout=TURN_TIMEOUT, session_id=...)`. `TURN_TIMEOUT`'s comment
becomes "How long the handshake, and then one reply, may take. A chat
turn, not a build." The rest of the class is as today.

### 4. Reading the work log: `_recorded()`

```python
#: The work-log line that names the session, author `engine`, so a
#: re-executed attempt finds it: the last such line in the run's log.
SESSION = "session "


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
```

`httpx` is a dependency of `athanore` (02 §Library choices) and needs
no addition. A failed read raises (`httpx.HTTPError`): the task fails
under rule 3 and the run with it (`retries=0`), which is the honest
outcome — a body that cannot read the run's log cannot know whether it
is continuing a conversation, and 23 §Refusal is explicit that quietly
starting over is the failure mode this feature removes. The API the
read needs is the one every agent of the run needs anyway. `YOU` and
`THEM` are defined above `_recorded` (move the two constants and their
comment up from the pane section to just under `STOP_WORDS`; they are
now the body's prefixes first and the pane's second).

### 5. The node: `talk`

```python
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
```

Points the implementer must keep:

- **The opener is message one**, as today: the run's title is the first
  thing said and is logged as `you: <title>` like any message. On
  re-execution it is message one again, so it is skipped by the same
  count as any replayed answer. A title that is a stop word ends the
  run with zero turns.
- **`open()` is entered before the first message**, as the task and 23
  §Surface say; the `session <id>` line is written before any prompt,
  so an attempt that dies during the first reply still leaves the id.
- **The `session` line is written on every execution**, continued or
  not; on a continued one it repeats the same id, and "the last such
  line" is then still right.
- **An empty message is asked again**, with the same prompt, and is
  not logged. Today's `(nothing said — say /quit to end)` line goes:
  a replayed empty answer would re-log it on every re-execution, and
  the pane cannot send one (`Say.text` has `min_length=1`).
- **No closing line.** Today's `wrap: N turns` is not written; the run's
  completion says the conversation ended and the returned transcript
  says how long it was.
- `zip(..., strict=False)`: `said` may be one longer than `replies`
  (a `you:` line without its reply, the crash-between-lines case);
  `history` is the answered pairs. Pyright standard is happy with the
  explicit keyword; ruff `B905` requires it.
- A `human_input` answer is coerced with `str(...)`, as today.
- `first` handles the opener only; `seen` counts messages that were
  neither empty nor a stop word — the same count the log's lines make.

### 6. One reply: `_reply()`

```python
async def _reply(session: AgentSession, said: str) -> str:
    """Ask the held session one thing and log what came back.

    Before the prompt, one ``notice`` chunk — ``you: <said>`` — goes to
    the transcript and is flushed: the reply's start, which is what
    ``draft`` pages from (one task carries every reply of the chat), and
    a line a reader of the transcript sees between one reply and the
    next. ``notice`` because it is the kind that is not the model's (03
    §StreamChunk). The reply itself is what the agent submitted; a
    failed turn's reply is its error, in parentheses, as today.
    """

    services = current_task().services
    await services.stream.append(ChunkKind.notice, f"{YOU}{said}")
    await services.stream.flush()
    result = await session.prompt(said)
    if result.ok:
        reply = result.output.reply.strip()
    else:
        reply = f"(turn {result.error})"
    await _log(f"{THEM}{reply}")
    return reply
```

The prompt is the message and nothing else — the assembly of 19 adds the
task block and the tier block as it does to every prompt (23 §Surface:
the façade does not edit what it is given, and the body wants nothing
shorter). `AgentSession` is imported from `athanore` (exported by T090).
`flush()` is what makes the marker durable and emits the `task.stream`
event before the prompt, so a pull that arrives during the reply finds
the marker already there.

### 7. The pane's data: `_pending`, `_answering`, `draft`

`_pending`:

```python
async def _pending(request: Request, run_id: str) -> Any:
    """The run's open request, or ``None`` while the agent is answering.

    One task, so at most one: the turn's ``human_input`` while it is the
    operator's turn, or an elicitation the agent raised mid-reply
    (``elicitation_policy="ask"``). If the agent ever has two open at
    once, the oldest is the one to answer first. (The store reach is as
    today: ...)
    """

    store = request.app.state.store
    if store is None:
        return None
    async with store.reader() as reader:
        views = await reader.requests.list_views(run_id, pending_only=True)
    return views[0] if views else None
```

Keep the existing paragraph about reading through the store; only the
first paragraph and the last line change (`views[0]`, oldest, was
`views[-1]`).

`_answering`:

```python
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
```

A rerun leaves a failed or cancelled row beside the live one; the
filter on `in_progress` is what makes "one" true.

`draft`, the one route whose body changes: after `chunks = await
reader.stream.list_after(task.id, after)`, drop everything up to and
including the last turn marker in the page —

```python
    # One task carries every reply of the chat, and the pane restarts
    # its cursor at 0 on each turn: the reply being typed is what follows
    # the turn's own marker, the `you:` notice the body wrote before it.
    for index in range(len(chunks) - 1, -1, -1):
        chunk = chunks[index]
        if chunk.kind == ChunkKind.notice and chunk.text.startswith(YOU):
            chunks = chunks[index + 1 :]
            break
```

— and return the `text` chunks of what is left, with `last_seq` as
today. A page pulled mid-reply (`after` past the marker) contains no
marker and is returned whole; a page pulled from 0 — the pane's first
pull of each reply, or a pane connecting mid-reply — is the whole
transcript once, then the cursor moves on. The docstring gains one
sentence saying so. `task_id`, `chunks`, `last_seq`: the response shape
is unchanged, and so is `static/chat.js`.

### 8. Imports

Add `from dataclasses import dataclass`, `import httpx`, and
`AgentSession` to the `from athanore import (...)` block (alphabetical:
`ACPAgent, AgentSession, PluginContext, PluginError, Workflow,
current_task, human_input`). `ChunkKind` and `TaskStatus` stay. `os`,
`Any`, `Request`, `BaseModel`, `Field`, `AGENT_SH`, `CHECKOUT` stay.
Nothing from `athanore.engine`, `athanore.store` beyond `rows` (already
imported), or `athanore.agents.acp` directly.

### 9. The module docstring

Rewritten whole. What it must say, in this order, in the voice of the
one it replaces (it is the seat's own documentation and the proof 23
§Why names):

1. `chat` — one agent, one operator, one session, turn after turn until
   you say stop. The smallest workflow with a model in it, and the
   proof 23 §Why asks for: one node, `talk`, opens the agent once with
   `open()` and holds it for the length of the conversation; every turn
   is a `human_input` that parks the task with its slot given back (a
   chat idles for hours and holds nothing while it does) and one
   `prompt()` on the same session; a stop word returns the transcript
   as the run's output.
2. **The agent's memory is its own.** The prompt is the message; the
   session has the rest. Nothing is pasted back, so a turn costs a
   turn. The session id is the one thing the body writes down — a
   `session <id>` line in the work log — because a server restart
   re-executes the attempt from its first line (D6), replays the
   answered questions (06 §Restart durability), and the body then
   re-opens *that* session (`continuing session` in the new transcript,
   05 §Continuing a session) rather than a blank one; a rerun does the
   same from the run's log. A session that cannot be continued is a
   refusal, not a fresh start (23 §Refusal).
3. **The agent is the sandbox's** — keep today's paragraph (`./scripts/
   agent.sh <pi|claude>`, `auto_allow`, elicitations asked, 05
   §User-land adapters, D75).
4. **The pane is the chat** — keep today's paragraph; add that a
   message still answers the run's open request, and that the pool slot
   (`talk`, capacity 2) counts replies being generated, not chats open
   (23 §What the pool slot means).
5. **The reply streams** — keep today's paragraph; add that one task
   carries every reply, so the body marks each turn's start in the
   transcript with a `you:` notice and `draft` pages from the last one.
6. `athanore submit chat "hello"`, then select the run and cycle to its
   `chat` pane — as today.

## Documents

- `docs/v1/17-serial-task-plan.md`: under T091's **Done.** paragraph,
  `**Status.** Done.` followed by the one-paragraph summary the other
  status lines carry: `talk` with `open()`, the `session <id>` engine
  line and `_recorded()` over `GET /api/agent/tasks/{id}`, the replay
  reconciliation, the `you:` transcript marker and `draft` paging from
  it, `_pending`/`_answering` one-or-none, `cwd`/`timeout` passed at
  construction, the docstring and system prompt, D267; and that the
  hand exercise was run on the fake (and on `pi`, if it was).
- `docs/v1/15-decisions.md`: one row, **D267**, "The boring readings
  of T091", `new (2026-09-12)`: (1) a body that must read its run's
  work log reads it as its agent does, `GET /api/agent/tasks/{id}` with
  the task token, because `TaskServices.log` is append-only and a read
  on it is a change to 04 the task does not make; the session to
  continue is the run's last `session <id>` engine line, from any
  attempt, so a rerun continues the conversation; (2) a re-executed
  attempt reconciles its replayed `human_input` answers against **this
  task's** `you:` and reply lines — the first `len(replies)` messages
  are skipped, a message with a `you:` line and no reply is prompted
  without a second line — so the agent is not re-asked what it already
  answered; (3) the body writes a `you: <message>` `notice` chunk to
  the transcript before each prompt and `draft` pages from the last
  one, because one task carries every reply and the pane restarts its
  cursor at 0 per turn; `notice` is the kind that is not the model's;
  (4) `ChatAgent` passes `cwd` and `timeout` at construction and drops
  the class attributes, which `ACPAgent.__init__` overwrites on every
  instance (05 §Agent classes lists both as constructor arguments); (5)
  an empty message is re-asked and not logged, and no closing line is
  written; (6) `_pending` takes the oldest open request, `_answering`
  refuses more than one `in_progress` task with a 500. Reason column:
  each is the reading that keeps the pane, the wire and the request
  channel unchanged, as T091's **Done.** requires, and the alternatives
  — a `LogService` read, a pane that tracks turn boundaries, a route
  that returns a turn number — change a layer the task fences.
- `docs/v1/23-session-continuity.md` §Why, first paragraph: "Its
  docstring says what it does today: every turn is a fresh ACP session,
  and the agent's memory is the last twenty turns of the transcript
  pasted into the assignment. That is honest and it works, and it is
  slow ..." becomes "Its docstring said what it did before T091: every
  turn was a fresh ACP session, and the agent's memory was the last
  twenty turns of the transcript pasted into the assignment. That was
  honest and it worked, and it was slow ..." (the tenses only; the
  paragraph's last sentence, "With a session held across turns ...",
  is already the present). No other document describes the seat's
  internals (`grep -rn "workflows/chat"` finds only registration
  examples).

Not touched: 05, 13, 02, the site, the skills, the generated reference
— none of them describes `workflows/chat` beyond its name.

## Tests

None in the gate: `workflows/` is dev machinery, and the gate lints and
type-checks it (`ruff`, `pyright` standard). No test file changes. The
existing suites must stay green untouched: `./scripts/test.sh`.

### Exercised by hand

The task's **Tests** block is a hand exercise; the implementer runs it
and **records what they saw in the run's work log** (the athanore run
this pipeline is, via `append_log`) and in the T091 status line. Two
passes: the first on the fake, which needs no credential and is
therefore not optional; the second on `pi`, only if `OPENROUTER_API_KEY`
is in the environment — if it is not, say so in the log rather than
skipping silently.

**Pass 1, on the fake.** From the worktree, in the dev container:

```sh
mkdir -p /tmp/t091/sessions
cat > /tmp/t091/chat.json <<'EOF'
{
  "sessions": {"dir": "/tmp/t091/sessions"},
  "prompts": [
    {"text": "first reply, typed", "submit": {"reply": "first reply"}},
    {"text": "second reply, typed", "submit": {"reply": "second reply"}},
    {"text": "a slow one, typed", "sleep_s": 8, "submit": {"reply": "slow reply"}},
    {"text": "another reply, typed", "submit": {"reply": "another reply"}}
  ]
}
EOF
PY="$(uv run python -c 'import sys; print(sys.executable)')"
export ATHANORE_HOST=127.0.0.1 ATHANORE_PORT=4102
export ATHANORE_DB_URL=sqlite+aiosqlite:////tmp/t091/athanore.db
export ATHANORE_AGENT_COMMAND="[\"$PY\", \"athanore/testing/fake_acp.py\", \"--scenario\", \"/tmp/t091/chat.json\"]"
uv run python -m workflows &          # the host; kill it with SIGINT for the restart step
A="uv run athanore --url http://127.0.0.1:4102"
```

`ATHANORE_HOST` must be overridden: the container's environment sets
`0.0.0.0`, which is a non-loopback bind and would demand the operator
token. `ATHANORE_AGENT_COMMAND` replaces `ChatAgent.command` (05 §Agent
classes), so no container is spawned and no key is needed; `sessions`
makes the fake persist the session on disk and advertise `loadSession`,
which is what the restart step needs; `prompts` scripts the replies in
order (23 §The fake); `sleep_s` on the third makes one reply slow
enough to watch its draft. Then:

1. `$A submit chat "hello"` → the run id `R`. `$A show R` after a
   moment: **one task**, `talk`, `waiting`; the log has `session <id>`
   (author `engine`), `you: hello`, `pi: first reply`, and one `[stats]
   … session=<id>` line. `$A requests R` shows one open request whose
   prompt is `pi: first reply\n\nyou:`.
2. `$A answer <req> "again"` → `pi: second reply`, a second `[stats]`
   line with the **same** `session=`, a new request. `curl -s
   'http://127.0.0.1:4102/api/plugins/chat/turns?run_id=R'` shows two
   turns and `pending` non-null.
3. `$A answer <req> "slowly"`, then within the 8 seconds: `curl -s
   'http://127.0.0.1:4102/api/plugins/chat/draft?run_id=R&after=0'` →
   `task_id` set and `chunks` carrying **only** `a slow one, typed` —
   not the two earlier replies' text; `$A stream <task>` shows the
   transcript with a `you: …` notice before each reply's text. After
   the reply lands, `draft?after=0` → `task_id: null`.
4. **Restart mid-chat**: with the fourth request open, SIGINT the
   server and start it again with the same environment. `$A show R`:
   the same task id, re-executed; a second `session <id>` line with the
   **same** id; `$A stream <task>` now carries `continuing session
   <id>` (05 §Continuing a session); the three answered turns were
   **not** re-asked and **not** re-answered (no new `you:`/`pi:` lines,
   no new `[stats]`); the open request is the same one, still pending.
5. `$A answer <req> "after the restart"` → `pi: another reply` (the
   fake re-runs its script from the first prompt on a new process, so
   the text is `prompts[0]`'s — expected, D122), `[stats]` with the
   same `session=`. Then `$A answer <req> "/quit"` → the run completes;
   `$A show R --json` (or the run's `output`) carries `{"agent": "pi",
   "session_id": "<id>", "turns": 4, "history": [...]}` with **this
   task's** four turns.
6. `ls /tmp/t091/sessions` → one session file. One task in the run
   throughout; one `[stats]` line per reply; one `session=` on all.

**Pass 2, on `pi`** (only with `OPENROUTER_API_KEY` exported and the
compose stack up — `./scripts/agent.sh pi` dispatches a sibling
container from inside the dev container through the mounted docker
socket): drop `ATHANORE_AGENT_COMMAND`, keep the rest, use a different
`ATHANORE_DB_URL`; the same steps 1–5 with real replies. What to look
for beyond pass 1: **a reply that starts without a container spawn**
(`docker ps` during the second reply shows the same `agent-pi`
container as during the first; `docker compose run` is not invoked
again), and that the second reply answers "what did I say first?"
correctly without any history in the prompt (`$A stream <task>` shows
the prompt was the message alone). The restart step shows pi's
`session/load` replay discarded (`replay discarded` at DEBUG in the
server log) and `continuing session` in the transcript.

Record, for whichever passes ran: the run id, the task id, the session
id, the count of `[stats]` lines, what `draft` returned mid-reply, and
what the restart did. If something did not match this list, that is a
finding for the log and for the status line, not something to smooth
over.

## Out of scope

- `static/chat.js` — byte-identical. The draft's start-of-reply is
  solved on the server side (§7) precisely so the pane is untouched.
- `workflows/__main__.py`: `talk`, capacity 2, unchanged (23 §What the
  pool slot means).
- The `turns` and `say` routes beyond `_pending`; the response shape
  of any route; `Say`, `Reply`, `STOP_WORDS`, `AGENT`, `MODEL`.
- A read on `TaskServices.log` or `RunService` (a change to 04 and the
  engine; D267 (1) says why the task API is used instead).
- The same `cwd`/`timeout` shadowing on `workflows/feature/agents.py`
  (`SandboxAgent.timeout = AGENT_TIMEOUT` is dead for the same reason;
  `steps.implement` passes `cwd=` explicitly, `timeout` falls to
  `settings.agent_timeout`). Note it in the work log as a finding for
  a `quick` run; do not fix it here.
- Whether `ACPAgent.__init__` should honour class-level `cwd` and
  `timeout` — a façade question for 05, not this seat.
- A transcript of the whole run (across reruns) in `talk`'s output: the
  output is this task's turns; the run's log is the whole conversation.
- Anything in `athanore/`, `tests/`, the wire, the SPA.

## Verification

```sh
./scripts/test.sh                                   # the gate, whole
./scripts/dev.sh "uv run ruff check workflows && uv run ruff format --check workflows && uv run pyright workflows"
git diff --exit-code tests/snapshots web/src/api/gen  # byte-identical
git diff --stat main -- workflows/chat/static/chat.js workflows/__main__.py   # empty
```

`uv run pyright` runs standard on `workflows/`: `Recorded` and
`_reply`'s annotations are given above; `result.output` is `Any` on
`AgentResult`, so `.reply` needs no cast. `ruff`: `B905` on `zip`
(`strict=False` given), `ASYNC` has nothing to say about
`httpx.AsyncClient`, `E501` at 88 — wrap the `PluginError` message in
`_answering`.

## Done

`workflows/chat` is one node, `talk`, on one `open()` block: the agent
is one process for the length of the conversation, the prompt is the
message, the session id is a `session <id>` engine line in the work log
and a re-executed or rerun attempt continues that session without
re-asking what was answered; `kickoff`, `turn`, `wrap`, `MEMORY` and
`_assignment` are gone; the system prompt and the module docstring say
what the seat is; `_pending` and `_answering` find the one; `draft`
pages from the turn's marker; `static/chat.js`, `workflows/__main__.py`,
the wire and the request channel are unchanged; the hand exercise ran
on the fake (and on `pi` if a key was there) and its findings are in
the work log and the status line; D267 is in 15, 23 §Why is in the past
tense, `**Status.** Done.` on T091; gate green; `tests/snapshots/
openapi.json` and `web/src/api/gen/` byte-identical.

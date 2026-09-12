# T090 — `ACPAgent.open()`: a session held open

**Task.** `docs/v1/17-serial-task-plan.md` § `### T090`.
**Specs.** `docs/v1/23-session-continuity.md` §A session held open, all
of it: §Why a second seam, §Surface, §Lifecycle of a held session, §What
the pool slot means, §Stats of a held session, §The fake, §Testing; and
§Scope (the "Also in scope, since 2026-09-12" paragraph, and the first
out-of-scope bullet, which bounds this task: a process held *within one
attempt*, never across attempts or runs); `docs/v1/05-agents.md` §Agent
classes, §AgentResult, §The ACP client, §Session lifecycle in
`ACPAgent.run()` (with §Continuing a session, which the entry step
reuses whole), §Stats entry, §Testing doubles; `docs/v1/13-testing.md`
§Pyramid (the *Agent façade* row) and §Fakes; `docs/v1/02-architecture.md`
§Package layout (the `agents/` block) and §Public API (the import block
`tests/test_public_api.py` parses); `docs/v1/19-agent-prompts.md`
§Repair turn (the fake tells a repair turn from a body's next prompt by
its first line, which is why 19 is byte-exact) and §Assembly (every
`prompt()` sends the full assembly); `docs/v1/04-engine.md` §Waiting and
§Shutdown (what cancellation records, and what the pool slot means
while a body is parked); D264 (the decision this task builds), D254–D256
and D265 (what T089 settled and this task reuses), D122 (a scenario
scripts one run — the rule `prompts` is an exception to).

This plan was written against the code as of `d0691fe` (T089 merged).
The façade is `athanore/agents/acp.py` (1447 lines): `run()` builds one
`_Session`, enters `declare(ctx)`, calls `_converse` and in its
`finally` runs `_cleanup` then `_record`; `_converse` builds the client,
`_spawn`s, then under `asyncio.timeout(self.timeout or
settings.agent_timeout)` calls `_exchange`, and maps every failure —
`AgentError` → `reason=transport` unless set, `TimeoutError` →
`timeout` + `AgentError("the agent did not finish within …s")`, any
other `Exception` → `transport` + `AgentError("the agent connection
failed: …")`, `CancelledError` → `reason=shutdown` (set in `run()`);
`_exchange` does `initialize`, `_tier`, `_open_session` (fresh
`session/new`, or T089's `_continue`), `_configure`, then
`render_prompt`, `_prompt`, `_repair`, `_outcome`. `_Session` carries
the process half (`process`, `connection`, `client`, `stderr`,
`session_id`) and the accounting half (`started`, `repair_turns`,
`status`, `reason`, `usage`, `entry`) in one dataclass; `ACPClient`
accumulates `text`, `tool_calls` and `denied_permissions` for the whole
process; `_entry` consults the provider's `stats()` whenever there is a
provider, a `session.session_id` and no `self.session_id`. Two `Spy`
classes in the tests override `_spawn(session, settings, ctx)` to keep
the child; that signature stays. The fake (`athanore/testing/fake_acp.py`,
1128 lines) counts `self.turn` per `session/prompt`: turn 0 runs
`first_turn()`, every later turn posts `repair_submit`; its helpers
(`first_turn`, `ask_permissions`, `ask_elicitations`, `emit_tool_calls`,
`call_mcp_tools`, `echo_env`) read `self.scenario`, which
`select_scenario` replaces per prompt in directory mode.

## What this task is

`ACPAgent.open()` returns an async context manager whose entry spawns
the adapter, `initialize`s, opens the session (`session/new`, or T089's
continuation when constructed with `session_id=`) and configures it,
all under `timeout`, and yields an `AgentSession` carrying `session_id`
and `prompt()`. Each `prompt()` is one assignment: the full assembly of
19, the turn under `timeout`, the repair loop, the outcome, then a
transcript flush and **one stats entry for that prompt**. The block's
exit flushes, closes the connection and stops the child, on every path,
and records nothing. A transport failure or a timeout inside a prompt
stops the child at once and every later `prompt()` raises `AgentError`
(`the session is closed: <reason>`); a refusal, a cancelled stop reason,
a truncated turn or a missing submission leaves the session open. A
second `prompt()` while one is in flight is `RuntimeError` before the
wire. `run(prompt)` becomes `open()` plus one `prompt()` on one code
path, its behaviour and its tests unchanged, including the provider's
`stats()` on its one entry — a held prompt's entry skips the provider
as a continued run's does (D256) and consults `final_stop_reason()` as
every entry does. `AgentSession` is exported from `athanore`. The fake
gains `prompts`: a list of per-prompt scenarios, the n-th scripting the
n-th body prompt of the session, the last repeating, repair turns
still posting `repair_submit`. 23 §A session held open is folded into
05 and 13; 02's public API block, the site guide, the workflows skill
and the generated reference follow; D266 records the boring readings
below; T090's `**Status.** Done.` line lands in the same commit.

Files touched, and nothing else: `athanore/agents/acp.py`,
`athanore/__init__.py`, `athanore/testing/fake_acp.py`,
`tests/agents/test_acp_lifecycle.py`, `tests/testing/test_fake_acp.py`,
`tests/test_public_api.py`, `docs/v1/02-architecture.md`,
`docs/v1/05-agents.md`, `docs/v1/13-testing.md`,
`docs/v1/15-decisions.md`, `docs/v1/17-serial-task-plan.md`,
`docs/v1/23-session-continuity.md` (two phrases, below),
`docs/site/src/guide/agents.md`, `scripts/_reference.py`,
`skills/athanore-workflows/SKILL.md`, and the generated pages
`docs/site/src/reference/{agents,python-api}.md` and
`skills/athanore-workflows/reference/{agents,python-api,guide-agents}.md`.
**Not** `athanore/agents/__init__.py` (decision 8 below), not the
engine, the store, the wire, `tests/snapshots/openapi.json` or
`web/src/api/gen/` — `git diff --exit-code` on the last two is part of
verification.

## The façade (`athanore/agents/acp.py`)

### 1. Two records where there was one

Split `_Session` into the half the block's exit deals with and the half
one prompt's entry is built from. Both stay private to the module.

```python
@dataclass
class _Session:
    """The process half of a held session: what open() spawned, what exit stops."""
    process: asyncio.subprocess.Process | None = None
    connection: ClientSideConnection | None = None
    client: ACPClient | None = None
    stderr: asyncio.Task[None] | None = None
    session_id: str | None = None
    #: The tooling tier the handshake chose; every prompt renders for it.
    tier: Tier = "http"
    #: Whether the block is the one-shot run(): one prompt, so its entry
    #: describes the whole session and may consult the provider (D256).
    whole: bool = False
    #: A prompt is in flight. A second one is a programming error.
    busy: bool = False
    #: Why the session is dead, once it is. Every later prompt() raises it.
    closed: str | None = None


@dataclass
class _Turn:
    """The accounting half: one prompt (or the entry handshake) and its entry."""
    started: float
    #: Where the client's whole-session counters stood when this turn
    #: began; the turn's numbers are the differences.
    text_at: int = 0
    tool_calls_at: int = 0
    denied_at: int = 0
    repair_turns: int = 0
    status: Literal["ok", "failed"] = "failed"
    reason: StatsReason | None = None
    usage: dict[str, int] = field(default_factory=dict)
    entry: dict[str, Any] | None = None

    def add_usage(self, reported: Any) -> None: ...   # today's, moved
```

The client's `text`, `tool_calls` and `denied_permissions` keep
counting for the whole process — a `client_class` subclass sees what it
saw before — and a turn reads its own share as `client.text[turn.
text_at:]`, `client.tool_calls - turn.tool_calls_at`, `client.
denied_permissions - turn.denied_at`. On a one-shot `run()` the offsets
are zero and the numbers are today's.

### 2. `open()`, `run()`, and the one context manager behind both

```python
def open(self) -> AbstractAsyncContextManager[AgentSession]:
    """Hold one session open for a block (05 §Holding a session, 23, D264)."""
    return self._session(whole=False)

async def run(self, prompt: str = "") -> AgentResult:
    async with self._session(whole=True) as held:
        return await held.prompt(prompt)

@asynccontextmanager
async def _session(self, *, whole: bool) -> AsyncIterator[AgentSession]:
    ctx = maybe_current_task()
    settings = AthanoreSettings()
    session = _Session(whole=whole)
    async with self.declare(ctx):
        handshake = _Turn(started=time.monotonic())
        try:
            await self._enter(ctx, settings, session, handshake)
        except BaseException:
            await self._cleanup(ctx, session)
            await self._record(ctx, session, handshake)
            raise
        assert session.session_id is not None
        try:
            yield AgentSession(
                session.session_id,
                partial(self._turn, ctx, settings, session),
            )
        finally:
            await self._cleanup(ctx, session)
```

- `open()` has exactly 23 §Surface's signature; `contextlib.
  AbstractAsyncContextManager` is the return annotation. `run()` is
  23's one line with the one flag the provider rule needs (`whole`),
  and the docs write it as `async with self.open() as s: return await
  s.prompt(prompt)` — which it is, in behaviour. (**Decision 7.**)
- `declare(ctx)` wraps the whole block, entry to exit, as it wraps a
  run today (23 §Lifecycle of a held session, step 1: the class is the
  configuration for the length of the block). `maybe_current_task()`
  is read when the block is entered, inside the body's bound context.
- Entry failure: the child is stopped, one entry is recorded from the
  handshake's `_Turn` (`failed/transport`, or `timeout`, or `shutdown`
  on a cancellation, as today), and the exception leaves `open()` —
  the block is never entered. `_record` on the handshake turn carries
  `session_id` only if the session was actually joined (a `_configure`
  that timed out after a successful `session/new`), which is the truth
  and what T089's refusal tests already assert (`session=` absent when
  nothing was joined).
- Exit: `_cleanup` and nothing else. **No entry at exit.**

### 3. Entry: `_enter` is today's `_exchange` without the prompt

```python
async def _enter(self, ctx, settings, session, turn: _Turn) -> None:
    async with self._bounded(turn, self._budget(settings)):
        client = self.client_class(self, ctx, _policies(self, settings))
        session.client = client
        await self._spawn(session, settings, ctx)
        conn = session.connection
        assert conn is not None
        initialized = await conn.initialize(...)          # today's, verbatim
        ...protocol version warning, verbatim...
        session.tier = self._tier(initialized, ctx)
        options = await self._open_session(session, client, initialized, session.tier, ctx)
        assert session.session_id is not None
        await self._configure(conn, client, session.session_id, options)
```

`_spawn`, `_open_session`, `_continue`, `_tier`, `_mcp_servers`,
`_resolve_config_id`, `_configure`, `_rejected` are untouched, including
`_spawn`'s `(session, settings, ctx)` signature the test `Spy`s
override. The whole of entry, spawn included, runs under `timeout` (23
step 1: "the whole of entry runs under `timeout`"); today the spawn is
outside the timeout and inside the mapping, and moving it inside
changes nothing observable. `_budget(settings)` is `self.timeout or
settings.agent_timeout`, spelled once.

### 4. The failure mapping, shared by entry and every prompt

```python
@asynccontextmanager
async def _bounded(self, turn: _Turn, budget: float) -> AsyncIterator[None]:
    """One step of the lifecycle under `timeout`, every failure named (05)."""
    try:
        async with asyncio.timeout(budget):
            yield
    except asyncio.CancelledError:
        turn.reason = "shutdown"          # a shutdown or a cancelled task; the numbers still stand
        raise
    except AgentError:
        if turn.reason is None:
            turn.reason = "transport"
        raise
    except TimeoutError:
        turn.reason = "timeout"
        raise AgentError(f"the agent did not finish within {budget}s") from None
    except Exception as exc:
        turn.reason = "transport"
        raise AgentError(f"the agent connection failed: {exc}") from exc
```

This is `_converse`'s mapping plus `run()`'s `CancelledError` clause,
moved, and the three messages are byte-identical to today's so the
existing `match=` assertions hold (`did not finish`, `connection
failed`, `auto_allow`). `_converse` and `_exchange` are deleted.

### 5. Each `prompt()`: `_turn`

```python
async def _turn(self, ctx, settings, session, prompt: str) -> AgentResult:
    if session.busy:
        raise RuntimeError(
            f"{type(self).__name__}: a prompt is already in flight on session "
            f"{session.session_id}; one prompt at a time"
        )
    if session.closed is not None:
        raise AgentError(f"the session is closed: {session.closed}")
    client = session.client
    assert client is not None
    turn = _Turn(
        started=time.monotonic(),
        text_at=len(client.text),
        tool_calls_at=client.tool_calls,
        denied_at=client.denied_permissions,
    )
    session.busy = True
    try:
        async with self._bounded(turn, self._budget(settings)):
            text = await self.render_prompt(prompt, ctx, tier=session.tier)
            response = await self._prompt(session, client, text, turn)
            response = await self._repair(ctx, session, client, response, turn)
            return await self._outcome(ctx, session, client, response, turn)
    except asyncio.CancelledError:
        session.closed = "the prompt was cancelled"
        raise
    except AgentError as exc:
        if turn.reason in ("transport", "timeout"):
            session.closed = str(exc)
        raise
    finally:
        session.busy = False
        if session.closed is not None and turn.reason != "shutdown":
            await self._cleanup(ctx, session)      # the child is stopped at once
        else:
            await self._flush(ctx)                 # the transcript, after every prompt
        await self._record(ctx, session, turn)
```

- Order of the two checks is 23's: `busy` first (`RuntimeError`,
  before the wire), then `closed` (`AgentError`). Neither records an
  entry: nothing was sent and nothing was spent (**decision 5**).
- `_prompt(session, client, text, turn)` calls `turn.add_usage`;
  `_repair(ctx, session, client, response, turn)` counts
  `turn.repair_turns` and uses it in the notice and `repair_prompt`;
  `_outcome(ctx, session, client, response, turn)` builds the result
  from the turn's share of the client's counters (`text="".join(
  client.text[turn.text_at:])`), sets `turn.status`/`turn.reason`, and
  calls `_entry(ctx, session, client, turn)`. `_truncated(session)` is
  unchanged. The bodies of the three are otherwise today's.
- What closes the session: `transport` (a dropped connection, a policy
  that could not be honoured — `client.failure` is raised by `_prompt`
  as an `AgentError` and mapped to `transport`, and 23 §The ACP client
  already says the session is broken after it), `timeout`, and a
  cancellation (**decision 3**: the agent was mid-turn and its state is
  unknown; the exit that follows stops it, so the prompt's own `finally`
  does not — 23 step 5: the entry is recorded, "and then the exit
  runs"). What leaves it open: `no_submission` (the process is fine;
  the body may prompt again — **decision 4**) and the failed results
  (`refusal`, `cancelled`, `truncated`), per 23 step 4.
- `_flush(ctx)` is the transcript flush pulled out of `_cleanup` under
  its `_logged` guard, so a prompt flushes without closing anything.
- The `closed` text is the `AgentError`'s message, so the second
  prompt's error reads `the session is closed: the agent did not finish
  within 0.5s` or `the session is closed: … auto_allow …`.

### 6. `_cleanup` runs at most once per resource

`_cleanup(ctx, session)` keeps its four guarded steps and sets
`session.connection`, `session.stderr` and `session.process` to `None`
after dealing with each, so the dead-session stop inside a prompt and
the block's exit may both call it and the second call only flushes the
transcript (**decision 10**). The SDK's `Connection.close()` is
idempotent already; `_stop` on a reaped child only `wait()`s; nulling
is what makes the intent visible. The `Spy`s in the tests keep their
own reference to the process from `_spawn`, so nulling changes no
assertion.

### 7. `_entry` and `_record` take the turn

```python
async def _entry(self, ctx, session, client, turn: _Turn) -> dict[str, Any]:
    if turn.entry is not None:
        return turn.entry
    provider_stats = None
    provider = self.stats_provider
    if (
        provider is not None
        and session.whole                      # a one-shot run() is the whole session
        and session.session_id is not None
        and self.session_id is None            # and not a continued one (D256)
    ):
        ...today's provider.stats() call...
    turn.entry = build_entry(
        node=..., attempt=...,
        status=turn.status, reason=turn.reason,
        duration_s=time.monotonic() - turn.started,
        model=self.model,
        usage=merge_usage(turn.usage or None, provider_stats),
        tool_calls=None if client is None else client.tool_calls - turn.tool_calls_at,
        session_id=session.session_id,
        repair_turns=turn.repair_turns,
        denied_permissions=0 if client is None else client.denied_permissions - turn.denied_at,
    )
    return turn.entry

async def _record(self, ctx, session, turn: _Turn) -> None:
    ...today's, with `self._entry(ctx, session, session.client, turn)`...
```

`duration_s` is the turn's, from `prompt()`'s entry to its outcome —
23 §Stats of a held session ("from its send to its outcome"); the
render's store read is inside it, as it is inside today's timeout. On
`run()` this drops the spawn and handshake from the one entry's
duration (**decision 2**); the resolution is whole seconds and no test
asserts it. `record_entry`'s identity guard is per `turn.entry`, so one
prompt records once whichever paths it took, and two prompts record two.

### 8. `AgentSession`

```python
class AgentSession:
    """A session held open by ``ACPAgent.open()``: its id, and ``prompt()``.

    ...05 §Holding a session; write session_id down; one prompt at a time...
    """

    def __init__(
        self, session_id: str, turn: Callable[[str], Awaitable[AgentResult]]
    ) -> None:
        #: The id the agent gave, or the one continued. It is the one thing
        #: a body should write down: a re-executed attempt hands it back
        #: as ``session_id=`` (23 §Lifecycle of a held session, step 6).
        self.session_id = session_id
        self._turn = turn

    async def prompt(self, prompt: str = "") -> AgentResult:
        """One assignment on the held session; the result is the prompt's."""
        return await self._turn(prompt)
```

A thin handle, so the reference page renders a constructor with no
private type in it and the lifecycle stays on `ACPAgent` where the
`Spy`s and the `client_class` seam expect it. Added to `acp.__all__`
beside `ACPAgent`. `session_id` is a plain attribute (23 §Surface
declares it as one), set at construction, which is after the session
is open.

### 9. Docstrings

The module docstring's "Stats are recorded exactly once, on every exit
path" bullet becomes once *per prompt*, none at exit; the `ACPClient`
docstring's "re-raised by `run()`" becomes `prompt()`; `_logged`'s
"`run()`'s `finally`" becomes the block's; `ACPAgent`'s class docstring
gains the two-line `open()` example of 23 §Surface after the subclass
example. Every rule 23 states about the held form is stated once, in
the docstring of the method that keeps it.

### 10. Exports

- `athanore/__init__.py`: `"AgentSession": ("athanore.agents.acp",
  "AgentSession")` in `_EXPORTS` under the agents comment, in `__all__`
  (sorted: after `AgentResult`), and in the `TYPE_CHECKING` import from
  `athanore.agents.acp`.
- `docs/v1/02-architecture.md` §Public API: the import block's agents
  line becomes `Agent, ACPAgent, AgentResult, AgentSession, AgentError,`
  — `tests/test_public_api.py` parses that block and fails both
  directions otherwise. §Package layout: `acp.py  ACPAgent,
  AgentSession + ACPClient`.
- `athanore/agents/__init__.py` is **not** touched (**decision 8**): it
  is a docstring and re-exports nothing — 02 §Package layout puts every
  name in `base.py` / `acp.py` — and an eager import there would pull
  `acp` in behind `from athanore.agents.base import Agent`. "Exported
  from `athanore.agents`" is `athanore.agents.acp.__all__`.

## The fake (`athanore/testing/fake_acp.py`)

1. **Vocabulary.** `"prompts"` joins `SCENARIO_KEYS`. A second constant:
   ```python
   #: What a per-prompt scenario under `prompts` may say: a turn's script.
   #: The keys the process consumes before or outside any prompt belong to
   #: the outer scenario and are refused here rather than silently ignored.
   PROMPT_KEYS = SCENARIO_KEYS - {
       "prompts", "sessions", "advertise_mcp", "config_options",
       "reject_config", "session_file", "request_log", "response_log",
   }
   ```
   23 names the first three as session-level; `reject_config` is read at
   `session/set_config_option` (before any prompt), `session_file` is
   written at process start, and the two logs are the process's — a
   per-prompt scenario carrying one of them would do nothing, which is
   the silent green 13 §Fakes forbids (**decision 6**).
2. **Validation.** `validate_scenario(scenario, *, where="scenario",
   keys=SCENARIO_KEYS)` — the "unknown key(s)" message quotes `keys`.
   `_validate_prompts(value, where)`: `None` passes; otherwise a
   non-empty list (empty is `ScenarioError(f"{where}.prompts: expected at
   least one scenario")`), each element run through
   `validate_scenario(item, where=f"{where}.prompts[{i}]",
   keys=PROMPT_KEYS)`.
3. **Telling a repair turn from the next prompt.** On the wire both are
   `session/prompt`. 19 §Repair turn is byte-exact and both of its
   texts open with the same words, so:
   ```python
   #: The first words of 19 §Repair turn, both texts. Under `prompts` a
   #: `session/prompt` opening with them is a repair turn of the prompt
   #: before it, not the next prompt of the session.
   REPAIR_MARKER = "Your turn ended, but no valid structured result"
   ```
   (`athanore/agents/submissions.py` `_REPAIR_REJECTED` and
   `_REPAIR_NOTHING` both begin so; the existing fake test already sends
   that prefix as its repair text.)
4. **`prompt()`.** Two new instance fields: `self.prompted = 0` (body
   prompts answered) and `self.script: dict[str, Any] = self.scenario`
   (the scenario the current turn is scripted by). After the recording
   and the directory-mode `select_scenario`:
   ```python
   turn = self.turn
   self.turn += 1
   prompts = self.scenario.get("prompts")
   if prompts is None:
       self.script, first = self.scenario, turn == 0          # D122, unchanged
   elif text.startswith(REPAIR_MARKER) and self.prompted:
       first = False                                          # a repair of self.script
   else:
       self.script = prompts[min(self.prompted, len(prompts) - 1)]
       self.prompted += 1
       first = True
   ```
   then today's body with `self.script` in place of `self.scenario`:
   `sleep_s`, `first_turn()` when `first` else `repair_submit`,
   `stop_reason`, `usage`. `first_turn`, `ask_permissions`,
   `ask_elicitations`, `emit_tool_calls`, `call_mcp_tools` and
   `echo_env` read `self.script`. `write_session_file`,
   `select_scenario`'s session-file write, `initialize`, `_open` and
   `set_config_option` keep reading `self.scenario`. Without `prompts`,
   `self.script is self.scenario` on every turn and nothing changes.
   A second process on a continued session starts at `prompted == 0`,
   so its first prompt runs `prompts[0]` — the same "first-turn script
   again" rule D257 gives the outer scenario.
5. Module docstring: one paragraph under the D122 one, saying what
   `prompts` is and how a repair turn is told apart, citing 23 §The fake
   and 19.

## Documents

**`docs/v1/05-agents.md`.**
- §Agent classes: the `ACPAgent` block gains `def open(self) ->
  AbstractAsyncContextManager[AgentSession]: ...` after `__init__`, and
  a third block follows it:
  ```python
  class AgentSession:                # what open() yields
      session_id: str                # once open
      async def prompt(self, prompt: str = "") -> AgentResult: ...
  ```
  After the `session_id=` paragraph, a paragraph on `open()`: a session
  held for a block, the loop example of 23 §Surface verbatim, the four
  bullets of that section condensed (no `close()`; `run(prompt)` is
  `async with self.open() as s: return await s.prompt(prompt)`; every
  prompt sends the full assembly of 19 and the façade edits nothing;
  `open()` on `session_id=` continues and holds; write `session_id`
  down), pointing at §Holding a session and D264.
- §AgentResult: "What one `run()` produced" → "…one `run()`, or one
  `prompt()` on a held session, produced".
- §Session lifecycle: after §Continuing a session, a new `### Holding a
  session` subsection: one sentence that `open()` is the seven steps
  above split at the block's edges, then 23 §Lifecycle of a held
  session's six numbered points folded as they stand (entry = steps
  1–3 under `timeout`, entry failure → child stopped, one entry,
  `AgentError`, block never entered; each `prompt()` = steps 4–6,
  `timeout` bounding one prompt and its repairs and nothing bounding the
  block, the node's own `timeout` paused while `waiting`; after each
  prompt the flush and one entry; a failed prompt — which reasons close
  the session and which leave it open, the `the session is closed:
  <reason>` message; exit = step 7 with no entry, on every path; after
  a crash the block is re-entered and `human_input` replays by
  ordinal), a seventh point for one-prompt-at-a-time (`RuntimeError`
  before the wire) and a session never shared between tasks, and a
  closing paragraph from §What the pool slot means (the pool caps agents
  *answering*; 04 §Waiting; D264). Two phrasings are corrected on the
  way in (see 23 below): a prompt in flight when the body is cancelled
  records `failed/shutdown`, as any cancelled run does (04 §Shutdown
  step 3), and the session is closed by it. One sentence says
  submissions are the attempt's (§Submissions): a second prompt on a
  class with an `output_model` attaches the attempt's latest valid
  submission, as two `run()`s in one body do today (**decision 9**).
- §Stats entry: "Recorded once per `run()`" → "…once per `run()` — once
  per `prompt()` on a held session (§Holding a session) —". A paragraph
  after the continued-run one, folding 23 §Stats of a held session: one
  entry per prompt with the held session's `session_id` on every one;
  `duration_s` from the prompt's send to its outcome; tokens ACP's
  per-turn `usage` or omitted; `tool_calls`, `repair_turns`,
  `denied_permissions` the prompt's; the provider's `stats()` not
  consulted on a held prompt (the same rule as a continued run, D256),
  `final_stop_reason()` on every prompt; no entry at exit; the one-line
  form unchanged, one line per reply.
- §Testing doubles, the `FakeACPAgent` bullet: "…usage), and `prompts`
  for a session held across several of them (13 §Fakes)".

**`docs/v1/13-testing.md`.**
- §Fakes, the vocabulary list: after `sessions`, `prompts: [scenario,
  ...]` (a list of scenarios, the n-th scripting the n-th body prompt of
  the session, the last repeating; each a scenario less `sessions`,
  `advertise_mcp`, `config_options`, `reject_config`, `session_file`,
  `request_log`, `response_log`; a `session/prompt` opening with 19
  §Repair turn's first words is a repair turn of the prompt before it
  and posts that prompt's `repair_submit`; 23 §The fake).
- The "A scenario scripts **one run**" bullet gains: "With `prompts`
  the n-th body prompt runs the n-th script's first turn; without it a
  held session's second prompt is the repair script, as `run()`'s tests
  rely on."
- §Pyramid, the *Agent façade* row: after the continued-sessions
  parenthesis, "; held sessions (`open()` on the fake's `prompts` key:
  one process for two prompts, one entry per prompt with one
  `session_id`, exit on exception and on cancellation, a dead session
  refusing later prompts, a refusal leaving it open, the concurrent
  `RuntimeError`, `open()` with `session_id=`, the provider's `stats()`
  only on `run()`, entry failure never entering the block, 23 §A
  session held open §Testing)".

**`docs/v1/02-architecture.md`.** §Public API and §Package layout as
in façade §10.

**`docs/v1/23-session-continuity.md`.** Two phrases, so 23 and 05 agree
after the fold (23's own rule: a disagreement is a bug in the fold):
in §Lifecycle of a held session step 5, "records its entry
`failed/cancelled` (or `shutdown`, on an engine stop) as it does today"
→ "records its entry `failed/shutdown`, as any cancelled run does today
(04 §Shutdown), and the session is closed by it"; in §Testing, "A
prompt cancelled mid-turn records `failed/cancelled`" →
"`failed/shutdown`". The façade cannot tell an operator's cancel from
an engine stop and never could; `cancelled` is ACP's stop reason and
stays the failed result of 23 step 4.

**`docs/v1/15-decisions.md`.** One row, **D266**, "The boring readings
of 23 §A session held open that T090 had to make", new (2026-09-12):
1. `asyncio.CancelledError` inside a held prompt records
   `reason=shutdown`, as `run()` does and 04 §Shutdown says; 23's
   `failed/cancelled` phrase is corrected. Reason: the façade cannot
   distinguish the two cancellations and `cancelled` is already ACP's
   stop reason.
2. `duration_s` is measured from `prompt()`'s entry to its outcome on
   every entry, `run()`'s included, so `run()`'s one entry no longer
   counts the spawn and handshake. Reason: one code path, 23's "from
   its send to its outcome", whole-second resolution.
3. A cancelled prompt closes the session too (later prompts raise `the
   session is closed: the prompt was cancelled`); the child is stopped
   by the exit that follows, not by the prompt. Reason: the agent was
   mid-turn; a body that swallowed the cancellation must not prompt an
   agent in an unknown state.
4. `no_submission` leaves the session open, with the three failed
   results. Reason: the process is fine; 23 closes it only for
   `transport` and `timeout`.
5. A `prompt()` refused for `busy` or `closed` records no entry.
   Reason: nothing reached the wire and nothing was spent (05 §Stats
   entry never zero-fills).
6. The fake tells a repair turn under `prompts` by 19 §Repair turn's
   first words, and `PROMPT_KEYS` also excludes `reject_config`,
   `session_file`, `request_log`, `response_log` and `prompts`. Reason:
   the wire does not distinguish the two `session/prompt`s and 19 is
   byte-exact for exactly this use; a key that would do nothing is
   refused rather than ignored.
7. `open()` and `run()` share one private `_session(*, whole)` context
   manager; `whole` is what lets `run()`'s one entry consult the
   provider (D256) while a held prompt's does not. Reason: the smallest
   flag that keeps 23's "one code path" and 05's provider rule both
   true.
8. `AgentSession` is exported from `athanore` (02 §Public API) and
   `athanore.agents.acp.__all__`; `athanore/agents/__init__.py` stays a
   docstring. Reason: façade §10.
9. Submissions stay the attempt's (05 §Submissions): a held session's
   later prompt attaches the attempt's latest valid submission. Reason:
   scoping submissions per prompt is the engine and the wire, out of
   23 §Scope; two `run()`s in one body already behave so.
10. `_cleanup` is idempotent (fields nulled as dealt with) so a dead
    session's immediate stop and the exit compose. Reason: the exit is
    a `finally` and must run on every path, including after a stop.

**`docs/v1/17-serial-task-plan.md`.** Under `### T090`, the `**Status.**
Done.` line naming what landed, in T089's style, in the same commit.

**`docs/site/src/guide/agents.md`.** After "## Continuing a session", a
"## Holding a session open" section: one paragraph on why (a body that
talks to one agent turn after turn pays a process per message
otherwise), the example inside a node body so it parses as a real
one —
```python
@wf.node(pool="talk")
async def talk(*, checkout: str) -> str:
    async with ChatAgent(cwd=checkout).open() as agent:
        while True:
            said = await human_input("Say something, or `stop`.")
            if said == "stop":
                return said
            reply = await agent.prompt(said)
```
— then: the block is the conversation, the process lives for it and is
stopped at its end on every path; each `prompt()` returns a result and
records a `[stats]` line of its own; a timeout or a transport failure
ends the session and later prompts raise `AgentError` ("the session is
closed"), while a refusal does not; write `agent.session_id` to the log
if the conversation is long, because a re-executed attempt hands it
back as `session_id=`; the pool counts agents answering, not agents
alive, so an open chat parked on a person holds no slot. "## Statistics"
gains "— per prompt, on a held session —" in its first sentence. Every
`python` fence on the page must parse (`tests/test_docs_site.py`).

**`skills/athanore-workflows/SKILL.md`.** One bullet after the
`session_id` one (the file is at 121 of 150 lines): "**To hold one
agent open for several turns inside one attempt, `async with
Agent(cwd=…).open() as held:` and `await held.prompt(text)` per turn**
— one process for the block, one `[stats]` line per prompt, the child
stopped at the block's exit on every path; a timeout or transport
failure closes the session and later prompts raise `AgentError`." The
"Where to read next" line for `guide-agents.md` gains "holding a
session open". No new fence.

**`scripts/_reference.py`.** `agents()` gains, between `ACPAgent` and
`AgentResult`, a `## AgentSession` block: a line "What `open()` yields;
`run()` is `open()` plus one `prompt()`.", the `session_id: str`
declaration (from `AgentSession.__annotations__` if the class annotates
it at class level — annotate it: `session_id: str` under the class
docstring, assigned in `__init__`), and `prompt`'s signature through
the existing `methods()` helper or one `signature()` line in its
style. `python-api.md` regenerates on its own from `__all__`.
`docs/site/src/reference/{agents,python-api}.md` and the skill's copies
are regenerated: `uv run scripts/gen_docs.py && uv run
scripts/gen_skills.py` — both pages and `guide-agents.md` must be
byte-for-byte what the scripts render (`tests/test_docs_site.py`,
`tests/test_skills.py`, CI's `contract` job).

## Tests

### `tests/testing/test_fake_acp.py` (raw client, 13 §Pyramid *Fake*)

A "The `prompts` key (23 §The fake)" section beside the sessions tests:

1. `test_prompts_script_successive_prompts_in_order_and_repeat_the_last`:
   `scenario(prompts=[{"text": ["one"]}, {"text": ["two"], "tool_calls":
   1}])`; handshake, three `prompt()`s with plain texts; the
   `agent_message_chunk`s are `["one", "two", "two"]` in order and the
   tool-call starts number 2 (one per "two" turn, none for "one").
2. `test_a_repair_turn_under_prompts_submits_the_prompt_it_follows`
   (with `task_api`, `task_env`): `prompts=[{"text": ["one"]}, {"text":
   ["two"], "repair_submit": {"ok": True}}]`; `prompt()`, `prompt()`,
   `prompt("Your turn ended, but no valid structured result…")`;
   `task_api.submissions == [{"ok": True}]`, no third text chunk, and a
   fourth plain `prompt()` is "two" again (the repair did not advance
   the list).
3. `test_without_prompts_the_second_prompt_is_the_repair_script` (with
   `task_api`, `task_env`): `scenario(text=["one"], repair_submit={"ok":
   True})`; two plain `prompt()`s — the second with ordinary text, not
   the repair marker; one "one" chunk and `task_api.submissions ==
   [{"ok": True}]` (D122 unchanged).
4. `test_a_prompts_element_may_not_carry_a_session_level_key`: for each
   of `sessions`, `advertise_mcp`, `config_options`, `reject_config`,
   `session_file`, `request_log`, `response_log`, `prompts`,
   `scenario(prompts=[{key: value}])` raises `ScenarioError` naming
   `prompts[0]`; and `scenario(prompts=[])` raises naming "at least one".
5. `test_prompts_on_a_loaded_session_start_from_the_first_script`
   (`tmp_path`): `sessions` + `prompts=[{"text": ["one"]}, {"text":
   ["two"]}]`; process one: handshake, two prompts; process two: `load`,
   one prompt → its live chunk is "one" (the second process's first
   prompt runs `prompts[0]`), and the replay before the load's answer
   is process one's recorded updates.

### `tests/agents/test_acp_lifecycle.py` (on the fake, 13 §Pyramid *Agent façade*)

A "Holding a session (23)" section after the continued-session one,
reusing `Fake`, `Spy`, `Recording`, `logs`, `methods`, `params_of`,
`sessions`, `first_run`. A helper:

```python
async def hold(agent: ACPAgent, ctx: TaskContext, *prompts: str) -> list[Any]:
    """Open `agent` once, prompt it with each text in order, close it."""
    with bind(ctx):
        async with agent.open() as held:
            return [await held.prompt(text) for text in prompts]
```

and a `DEADLINE = 10.0` fuse for the cancellation and concurrency tests
(as `test_acp_outcomes.py` has).

1. `test_two_prompts_share_one_process_and_one_session` (`context`,
   `transcript`, `stats_lines`, `logs`): `Spy(command=scenario(prompts=
   [{"text": ["one"], "tool_calls": 1}, {"text": ["two"], "tool_calls":
   2, "sleep_s": 2}], request_log=str(logs)))`; inside the block, after
   the first prompt, `agent.process.returncode is None`; after it, not
   `None`. `methods(logs).count("initialize") == 1`, `count("session/
   new") == 1`, `count("session/prompt") == 2`. `first.text == "one"`,
   `second.text == "two"` (the second is not "onetwo"); `first.
   session_id == second.session_id == held.session_id` (capture it in
   the block); the transcript is `("text","one")`, tool 1's pair,
   `("text","two")`, tool 1's pair, tool 2's pair, in that order; two
   `[stats]` lines both carrying `session=<sid[:8]>`; `first.stats
   ["tool_calls"] == 1`, `second.stats["tool_calls"] == 2`; `second.
   stats["duration_s"] >= 2` and `first.stats["duration_s"] <= 1`.
2. `test_run_is_open_plus_one_prompt`: `Spy` with `scenario(text=
   ["done"], tool_calls=1, request_log=…)`, `run()`; one `session/new`,
   one `session/prompt`, `returncode` set, one `[stats]` line, `result.
   text == "done"`, `tool_calls == 1`. (Every existing lifecycle and
   outcomes test is the rest of this assertion.)
3. `test_an_exception_in_the_block_stops_the_child_and_records_nothing_more`:
   `Spy`, `prompts=[{"text": ["one"]}]`; in the block one prompt then
   `raise RuntimeError("body")`; `pytest.raises(RuntimeError)` outside;
   `returncode` set; exactly one `[stats]` line (the prompt's, `ok`).
   And the zero-prompt variant in the same test or its own: a block
   that opens and raises at once records **no** line.
4. `test_a_cancelled_prompt_records_shutdown_and_the_exit_stops_the_child`
   (`served_context` or `context`, `stats_lines`): `Spy`, `prompts=
   [{"text": ["one"]}, {"sleep_s": 30}]`; a body task that opens,
   prompts once, sets an `asyncio.Event`, prompts again; the test waits
   on the event, sleeps `0.2`, cancels the task under `DEADLINE`,
   `pytest.raises(asyncio.CancelledError)`; `returncode` set; two
   `[stats]` lines, the second `failed (shutdown)`.
5. `test_a_timeout_closes_the_session_and_the_next_prompt_is_refused`:
   `Spy`, `agent.timeout = 0.5`, `prompts=[{"sleep_s": 30}, {"text":
   ["never"]}]`, `request_log`; in the block: `pytest.raises(AgentError,
   match="did not finish")` on the first prompt, then `agent.process.
   returncode is not None` **inside the block** (stopped at once), then
   `pytest.raises(AgentError, match=r"the session is closed: the agent
   did not finish within 0\.5s")` on the second; one `session/prompt` on
   the wire; one `[stats]` line, `failed (timeout)`.
6. `test_a_transport_failure_closes_the_session_and_the_next_prompt_is_refused`
   (`served_context`): `Spy`, `prompts=[{"permissions": [{"options":
   [{"kind": "reject_once"}]}]}, {"text": ["never"]}]` under
   `auto_allow` (the policy that cannot be honoured — the same failure
   `test_a_policy_that_cannot_be_honoured_fails_the_run` uses);
   `match="auto_allow"` on the first, `returncode` set inside the block,
   `match="the session is closed: .*auto_allow"` on the second; one
   `session/prompt`; one `[stats]` line `failed (transport)`.
7. `test_a_refusal_leaves_the_session_open`, parametrized over
   `stop_reason` in `("refusal", "cancelled")`: `prompts=[{"stop_reason":
   stop}, {"text": ["two"]}]`; `first.ok is False`, `first.error ==
   stop`, `second.ok` and `second.text == "two"`; two `session/prompt`;
   two `[stats]` lines, the first `failed (<stop>)`. And
   `test_a_missing_submission_leaves_the_session_open` (`served_context`,
   an `output_model` subclass with `max_repair_turns = 0`): `prompts=
   [{}, {"submit": {"verdict": "ok"}}]`; first `pytest.raises(AgentError)`
   (no submission), second `ok` — decision 4 pinned.
8. `test_a_second_prompt_while_one_is_in_flight_is_a_runtime_error`:
   `prompts=[{"text": ["one"], "sleep_s": 1}]`, `request_log`; in the
   block `first = asyncio.create_task(held.prompt("a"))`, `await
   asyncio.sleep(0.1)`, `pytest.raises(RuntimeError, match="already in
   flight")` on `held.prompt("b")`, then `await first` is ok; exactly
   one `session/prompt` in the log; one `[stats]` line.
9. `test_open_with_a_session_id_continues_it_once_then_prompts`,
   parametrized `(resume, method)` as T089's unknown-id test:
   `first_run(...)` → `sid`; `Fake(command=scenario(sessions={…,
   "resume": resume}, prompts=[{"text": ["two"]}, {"text": ["three"]}],
   request_log=…), cwd=cwd, session_id=sid)`; in the block `held.
   session_id == sid`, two prompts; `methods(logs)[:2] == ["initialize",
   method]`, `count(method) == 1`, no `session/new`, two `session/
   prompt`; `a.text == "two"`, `b.text == "three"`; the transcript is
   `("notice", f"continuing session {sid}")` then the two texts;
   both results and both entries carry `sid`.
10. `test_the_provider_is_asked_for_a_stop_reason_on_every_prompt_and_for_stats_only_by_run`:
    a `Recording` provider on a held `Fake` with `prompts=[{}, {}]` →
    `provider.called == [("final_stop_reason", sid), ("final_stop_reason",
    sid)]` and neither entry carries `cost`; the same provider class on
    a `run()` → `[("final_stop_reason", sid), ("stats", sid)]` and the
    entry carries `cost` (T089's test already proves the continued-run
    half; this one is the held half beside the one-shot half).
11. `test_an_initialize_failure_raises_from_open_and_never_enters_the_block`
    (`stats_lines`): `Spy(command=[sys.executable, "-c", "import sys;
    sys.stdin.readline(); sys.exit(1)"])` — a child that reads the
    `initialize` line and exits without answering, so the SDK rejects
    the pending request with `ConnectionError` (its receive loop's EOF
    `_disconnect`); `pytest.raises(AgentError, match="connection
    failed")` around `agent.open()`; a flag set inside the block stays
    unset; `returncode` set; one `[stats]` line, `failed (transport)`,
    no `session=`.

The module docstring's list gains a sixth bullet: **A session held open
is one process and one entry per prompt.** The existing tests are not
edited.

### `tests/test_public_api.py`

`test_agent_session_is_exported_beside_agent_result`: `"AgentSession"`
in `athanore.__all__` and in `documented_surface()`, and `athanore.
AgentSession is athanore.agents.acp.AgentSession`. The parametrized
suites pick the name up from 02 on their own.

## Out of scope

- A process held across attempts or runs; `session/fork`, `list`,
  `delete`, `close`; a fallback to `session/new` on a failed
  continuation; the façade editing prompt text; anything past the
  façade (23 §Scope). T091 rewrites the `chat` seat on this.
- Scoping submissions per prompt (decision 9).
- A `close()` method, a `prompt()` that takes a timeout of its own, a
  block-level timeout (23 §Lifecycle step 2: the node's `timeout` is the
  bound on the block).
- Changing `04-engine.md` for the pool-slot meaning: D264 records it and
  05 §Holding a session states it; 04 §Waiting already describes the
  mechanism.

## Verification

```sh
./scripts/test.sh                                   # the gate
./scripts/test.sh -k "acp_lifecycle or fake_acp or public_api or acp_outcomes"
./scripts/dev.sh "uv run scripts/gen_docs.py && uv run scripts/gen_skills.py"
git diff --exit-code tests/snapshots web/src/api/gen  # byte-identical
```

`uv run pyright` is standard on `athanore.agents`; the two new
dataclasses and the two `asynccontextmanager`s are annotated
(`AsyncIterator[None]`, `AsyncIterator[AgentSession]`). `uv run
lint-imports`: `acp.py` gains `functools.partial`, `contextlib.
asynccontextmanager`, `contextlib.AbstractAsyncContextManager` and
`collections.abc.Awaitable, Callable, AsyncIterator` — nothing from the
package.

## Done

`ACPAgent.open()` yields an `AgentSession`; a body prompts it as often
as it likes on one process, with one stats entry per prompt, none at
exit, the same cleanup on every exit and a dead session refusing later
prompts; `run()` is that with one prompt and every existing test is
green untouched; the fake scripts a held session's prompts with
`prompts`; 05 and 13 say so, 02 exports the name, 23 agrees with 05,
D266 is in 15, the site guide and the skill show the loop, the
reference is regenerated; `**Status.** Done.` on T090; gate green;
`tests/snapshots/openapi.json` and `web/src/api/gen/` unchanged.

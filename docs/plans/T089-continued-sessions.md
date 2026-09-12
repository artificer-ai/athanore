# T089 — `ACPAgent(session_id=)`: one session across runs

**Task.** `docs/v1/17-serial-task-plan.md` § `### T089`.
**Specs.** `docs/v1/23-session-continuity.md` §Surface, §Lifecycle of a
continued run (with §The replay is not this attempt's transcript and
§Refusal), §Stats, §Testing (the **Façade** and **Public API** bullets;
the **Fake** bullet is T088's and landed), §Scope, §Terms;
`docs/v1/05-agents.md` §Agent classes, §The ACP client, §Session
lifecycle in `ACPAgent.run()`, §Stats entry; `docs/v1/13-testing.md`
§Pyramid (the *Agent façade* row) and §Fakes (the `sessions` key, as
T088 wrote it); `docs/v1/19-agent-prompts.md` (nothing changes — the
assembly is byte-exact and a continued run sends the same prompt);
`docs/v1/12-security.md` §Task tokens (a continued session is not a
continued token); D254 (`session_id=` on construction, no fallback),
D255 (`resume` before `load`, the replay discarded under a flag), D256
(no provider `stats()` on a continued run, no `resumed` field), D258
(the `continuing session` notice on both paths), D259 (what the fake
records and replays).

This plan was written against the code as of `ee84ffb`. The façade is
`athanore/agents/acp.py` (1303 lines): `ACPAgent.__init__` takes
`command`, `cwd`, `timeout`, `env`; `_exchange` does `initialize`,
`_tier`, `conn.new_session(...)`, `session.session_id = started.
session_id`, `_configure(conn, client, started)` and then prompts;
`_configure` and `_resolve_config_id` take a `NewSessionResponse` and
read `.session_id` and `.config_options` off it; `ACPClient.
session_update` maps the four kinds of 05 onto chunks, appends text to
`client.text` and counts `tool_call`; `_entry` consults
`self.stats_provider.stats()` whenever there is a provider and a
`session.session_id`; `_truncated` consults `final_stop_reason()` the
same way. The fake (`athanore/testing/fake_acp.py`, T088) answers
`session/load` by re-sending its file's updates *before* its response
on the same pipe, answers `session/resume` with nothing before its
response, and is `-32602 no such session: <id>` on an unknown id.

Two facts about the SDK (`agent-client-protocol` 0.12.1, in the
container's venv) that the design below leans on, verified by reading
`acp/client/connection.py`, `acp/connection.py`, `acp/router.py`:

- `ClientSideConnection.load_session(cwd, session_id, mcp_servers=None,
  ...)` → `LoadSessionResponse` and `resume_session(session_id, cwd,
  mcp_servers=None, ...)` → `ResumeSessionResponse`. Both responses
  carry `config_options` and `modes` and **no `session_id`** — the id
  is the one we sent. `load_session` substitutes `[]` for
  `mcp_servers=None` on the wire (as `new_session` does);
  `resume_session` does not, and sends no `mcpServers` key at all.
- An agent's JSON-RPC error answer surfaces as `acp.RequestError(code,
  message, data)` raised from the awaited call; `str(exc)` is the
  agent's `message`. A dropped connection is `ConnectionError`.
- **Ordering of the replay against the response.** The connection's
  receive loop turns each incoming `session/update` into an asyncio
  task (`_tasks.create`) in arrival order, and resolves the pending
  request's future when the response line arrives. Tasks created
  before the future is resolved are scheduled ahead of the waiter, and
  the whole dispatch chain from the task's first step down to
  `ACPClient.session_update` — `_run_notification`, the router,
  `_make_func`'s wrapper, `_SessionUpdateTracker.session_update` —
  contains no suspension point before our method runs. So a
  `session_update` that checks `replaying` **before its first
  `await`** sees the flag set for every update the agent sent before
  its `session/load` response, whichever way the pipe was buffered.
  The façade test on the fake (below) is the proof, and its transcript
  assertion is exact for that reason.

## What this task is

`ACPAgent(session_id=...)` makes a run continue a session an earlier
run opened: after `initialize`, `session/resume` when the agent
advertises `sessionCapabilities.resume`, else `session/load` when it
advertises `loadSession`, else `AgentError` before any prompt; both
calls carry the `cwd` and `mcp_servers` a `session/new` would; the
replay a `session/load` produces is discarded from the transcript, the
text and the counters under `client.replaying`; the attempt's
transcript opens with one `notice`, `continuing session <id>`; the
session's config options are set by category as on a fresh run; the
provider's `stats()` is not consulted on a continued run; every
failure records the ordinary `failed/transport` entry, without a
`session_id` when the session was never joined. 23 §Surface,
§Lifecycle of a continued run and §Stats are folded into 05; 13's
pyramid row names the behaviour; the site guide and the workflows
skill say how to use it; the generated reference follows the new
signature.

Nothing outside `athanore/agents/acp.py`, `tests/agents/
test_acp_lifecycle.py`, the documents named below and the generated
pages is touched. `athanore/testing/` is not touched (T088 gave the
fake everything this needs; `FakeStatsProvider` is subclassed in the
test, not changed). `tests/snapshots/openapi.json` and `web/src/api/
gen/` are not regenerated and `git diff --exit-code` on them is part
of verification: nothing on the wire changes.

## The façade (`athanore/agents/acp.py`)

1. **The argument.** `ACPAgent.__init__(self, command=None, cwd=None,
   timeout=None, env=None, session_id: str | None = None)`, stored as
   `self.session_id` with a `#:` comment beside `cwd`'s: the session
   an earlier run left behind, to be continued rather than a new one
   opened (23 §Surface, D254); `AgentResult.session_id` is where it
   comes from, and `cwd` has to be the one the session was opened
   with. A run is **continued** when `self.session_id is not None`;
   there is no separate flag on `_Session`. An empty string is not
   special-cased: it is handed to the agent, whose refusal (`no such
   session`) is the honest answer (**decision**, for 15).

2. **The client's replay state.** `ACPClient.__init__` gains two
   public attributes with `#:` comments: `self.replaying: bool =
   False` (set by the façade around `session/load` and nowhere else)
   and `self.replayed: int = 0` (how many `session/update`s arrived
   while it was set). `session_update` starts with:
   ```python
   if self.replaying:
       self.replayed += 1
       return
   ```
   — before the kind lookup, before any `await`. Every update received
   under the flag is counted, whatever its kind: `user_message_chunk`,
   a plan update, the four kinds 05 transcribes. The replay is defined
   as the notifications sent between `session/load` and its answer
   (23 §Terms), so the number a reader of the DEBUG line gets is that
   (**decision**: count every update, not only the transcribable
   ones). `request_permission`, `create_elicitation` and everything
   else on the client do not read the flag (23 §The replay is not this
   attempt's transcript: the policy's answer is the honest one either
   way; a dropped request would hang the adapter).

3. **Opening the session, one way or the other.** Split the middle of
   `_exchange` out. After `tier = self._tier(initialized, ctx)`:
   ```python
   options = await self._open_session(session, client, initialized, tier, ctx)
   assert session.session_id is not None
   await self._configure(conn, client, session.session_id, options)
   ```
   `_open_session(...) -> Sequence[Any] | None` returns the response's
   `config_options` and sets `session.session_id` on success:
   - **fresh** (`self.session_id is None`): today's `conn.new_session(
     cwd=self.cwd or os.getcwd(), mcp_servers=self._mcp_servers(tier,
     ctx))`, `session.session_id = started.session_id`, return
     `started.config_options`. Byte-identical on the wire to today.
   - **continued**: `self._continue(session, client, conn,
     initialized, tier, ctx)`, below.

4. **`_continue`** (23 §Lifecycle step 2, §Refusal, D255):
   ```python
   capabilities = initialized.agent_capabilities
   sessions = capabilities.session_capabilities if capabilities else None
   resume = sessions is not None and sessions.resume is not None
   load = capabilities is not None and bool(capabilities.load_session)
   if not resume and not load:
       raise AgentError(
           f"{type(self).__name__} cannot continue a session: the agent "
           "advertises neither session/resume nor session/load"
       )
   cwd = self.cwd or os.getcwd()
   servers = self._mcp_servers(tier, ctx) or []
   try:
       if resume:
           opened = await conn.resume_session(
               session_id=self.session_id, cwd=cwd, mcp_servers=servers
           )
       else:
           client.replaying = True
           try:
               opened = await conn.load_session(
                   cwd=cwd, session_id=self.session_id, mcp_servers=servers
               )
           finally:
               client.replaying = False
               _log.debug(
                   "replay discarded",
                   agent=type(self).__name__,
                   session_id=self.session_id,
                   count=client.replayed,
               )
   except RequestError as exc:
       raise AgentError(
           f"the agent could not continue session {self.session_id}: {exc}"
       ) from exc
   session.session_id = self.session_id
   await client.append("notice", f"continuing session {self.session_id}")
   return opened.config_options
   ```
   Points that are the plan, not the implementer's call:
   - `resume` is read as *the capability object is present* (`{}` is
     the SDK's `SessionResumeCapabilities`, an empty model); `load` as
     `loadSession` truthy. `AgentCapabilities.session_capabilities`
     defaults to an empty `SessionCapabilities()` whose `resume` is
     `None`, and `load_session` defaults to `False`, so an agent that
     advertises nothing (the fake without `sessions`) refuses.
   - `mcp_servers` is `self._mcp_servers(tier, ctx) or []` on **both**
     calls, so the wire carries `mcpServers: []` outside the `mcp` tier
     exactly as `session/new` does (the SDK substitutes `[]` for `load`
     and `new` but not for `resume`; the façade does not depend on
     that) (**decision**). In the `mcp` tier the one server carries
     **this** task's token, because `_mcp_servers` reads `ctx` — 23
     §Lifecycle step 1 (a continued session is not a continued token).
   - The `replaying` flag is set immediately before `load_session` and
     cleared in a `finally`, so a `RequestError`, a `ConnectionError`,
     a cancellation and a timeout all clear it; the DEBUG line is
     written once, when it clears, on every path. `session/resume`
     never sets it.
   - Only `RequestError` is translated. Anything else raised by the
     call (`ConnectionError`, a validation error on a malformed
     response) falls through to `_converse`'s existing `except
     Exception` → `AgentError("the agent connection failed: ...")`,
     reason `transport` — what a fresh run already does for the same
     failure at `session/new` (**decision**: no new branch for it).
   - `session.session_id` is set **after** the call returns and before
     the notice: a run that raised in `_continue` leaves it `None`, so
     `_truncated` does not consult the provider, `_entry` does not
     name a session, and `AgentResult` is never built (23 §Lifecycle
     step 2, §Refusal).
   - The notice goes through `client.append` **before** `_configure`
     runs, so the continued attempt's transcript *opens* with it even
     when a config option is rejected and `_rejected` writes its own
     notice next (23 §Lifecycle step 3: "opens with"; **decision** on
     the order relative to configuration notices). It is written on
     both paths (D258).

5. **`_configure` and `_resolve_config_id` take what both responses
   have.** Signatures become `_configure(self, conn, client,
   session_id: str, options: Sequence[Any] | None)` and
   `_resolve_config_id(self, options: Sequence[Any] | None, category:
   str)`; the bodies are unchanged except that `started.config_options
   or []` becomes `options or []` and `session_id=started.session_id`
   becomes `session_id=session_id`. The `NewSessionResponse` import
   stays for `_open_session`'s fresh branch. Nothing outside the
   module calls either (grep confirms); the docstrings keep their D11
   / 20 §Finding 2 text. The continued session is therefore re-told
   the class's `model` and `thinking` exactly as a new one is,
   rejections logged and written as `notice` (23 §Lifecycle step 2).

6. **`_entry`: no provider `stats()` on a continued run** (23 §Stats,
   D256). The guard becomes
   ```python
   if provider is not None and session.session_id is not None and self.session_id is None:
   ```
   with a comment: a provider reports a whole session and a continued
   run is a fraction of one; tokens are ACP's per-turn `usage` or
   omitted (`merge_usage(session.usage or None, None)`), `model` is the
   class's. `_truncated` is **unchanged**: `final_stop_reason()` is
   consulted whenever there is a provider and a joined session, on
   both paths. Update `_entry`'s docstring (the "second source"
   paragraph gains the sentence).

7. **Failure accounting needs no new code**, and the plan says so, so
   the implementer does not add any: the refusal and the translated
   `RequestError` are `AgentError`s raised inside `_exchange`, caught
   by `_converse`'s `except AgentError` (reason `transport`), and
   `run()`'s `finally` runs `_cleanup` (child stopped, `returncode`
   set) then `_record` (one entry, `failed/transport`, no `session_id`
   because `session.session_id` is still `None`). The tests below
   assert each of those from the outside.

8. **Docstrings.** The module docstring's rule list gains one bullet
   after "Stats are recorded exactly once…": *A replay is history, not
   this attempt's transcript* — under `replaying`, a `session/load`'s
   re-sent updates write no chunk, add no text and count no tool call;
   they were recorded by the attempt that ran them (23, D255).
   `ACPClient`'s docstring gains one sentence on the flag beside "it
   **transcribes**… it **counts**". `ACPAgent.run`'s docstring: the
   handshake line becomes "spawn, handshake, open a session — a new one,
   or the one `session_id` names — configure it by category…".
   `_exchange`'s one-liner stays. Everything cites sections by number
   (`23 §Refusal`), never by path — `tests/test_spec_citations.py`
   forbids `docs/v1/` in the package.

9. **Types and lint.** `pyright` standard applies to `athanore/agents/`;
   `LoadSessionResponse | ResumeSessionResponse | NewSessionResponse`
   all expose `config_options` as the same union list, so `Sequence[Any]
   | None` for `options` is honest without a new alias. `ruff` line
   length 88. `lint-imports`: `acp` is already imported here; nothing
   new from the package.

## Documents

10. **`docs/v1/05-agents.md`.**
    - §Agent classes: the signature line becomes
      `def __init__(self, command=None, cwd=None, timeout=None, env=None, session_id: str | None = None): ...`
      and, after the `template=` paragraph, one paragraph: `session_id=`
      continues a session an earlier run opened (`AgentResult.
      session_id` is where it comes from; `cwd` MUST be the one the
      session was opened with, and the agent enforces it); the run
      either continues it or raises — never a `session/new` in its
      place — per §Continuing a session below; 23 §Surface, D254.
      Include 23's two-line example (`first = await Reviewer(cwd=…).
      run(...)`; `again = await Reviewer(cwd=…, session_id=first.
      session_id).run(...)`).
    - §The ACP client, the `session_update` bullet: add "while the
      client is `replaying` — the façade sets it around a `session/
      load` — an update writes no chunk, adds no text and counts no
      tool call; it is counted and logged once at DEBUG (`replay
      discarded`, `count=`); `request_permission` and
      `create_elicitation` are answered as ever (§Continuing a
      session)".
    - §Session lifecycle step 2: "`initialize` (…), then
      `new_session(cwd, mcp_servers)` — or, on an agent constructed
      with `session_id=`, the re-open of §Continuing a session — and
      set `model` / `thinking` by category from the response's
      `configOptions`, whichever method answered."
    - A new `### Continuing a session` after step 7's paragraphs and
      before `### Truncation detection is a provider concern`, the fold
      of 23 §Lifecycle of a continued run, §The replay is not this
      attempt's transcript and §Refusal, pointing at 23 for the why.
      Content, in this order: (a) spawn is unchanged and the token is
      this task's; (b) after `initialize`, `session/resume` when
      `agentCapabilities.sessionCapabilities.resume` is present, else
      `session/load` when `agentCapabilities.loadSession`, else
      `AgentError` `<Agent> cannot continue a session: the agent
      advertises neither session/resume nor session/load` before any
      prompt with the child stopped; both take `session_id`, `cwd`
      (`self.cwd or os.getcwd()`) and the tier's `mcp_servers`; `resume`
      first because it is cheaper and produces nothing to discard, `load`
      because it is the one every persisting adapter has (D255); the
      response's `configOptions` configured as a `session/new`'s;
      `session.session_id` set only when the call succeeds; (c) the
      replay: between sending `session/load` and its response the
      client is replaying — no chunk, no text, no `tool_calls`, requests
      still answered — the flag set around that one call and cleared on
      every path, `resume` never setting it, the dropped count logged
      once at DEBUG; why discard (the replayed turns already have a
      transcript; a `StreamChunk` belongs to the task that produced it,
      03); (d) the notice, `continuing session <session_id>`, the first
      chunk of the attempt's transcript on both paths (D258); (e)
      prompt, repair and outcome unchanged, the repair loop on the
      continued session; (f) refusal: the three cases of 23 §Refusal
      with the exact messages, each recording `failed/transport` with no
      `session_id`, and no fallback to `session/new` (D254, the
      `auto_allow` precedent in §Policies). Keep 05's register — the
      numbered-step, one-fact-per-sentence style of §Session lifecycle —
      and its MUST/SHOULD where 23 uses them.
    - §Stats entry: after "Fields that cannot be determined are
      omitted. Never raises.", one paragraph: on a continued run the
      provider's `stats()` is not consulted — it reports a session, and
      a continued run is a fraction of one — so `input_tokens`,
      `output_tokens`, `total_tokens` and `cost` are ACP's per-turn
      `usage` or omitted, `model` is the class's, `final_stop_reason()`
      is still consulted, and `session_id` is the continued session's,
      so every run on one session carries one id and no `resumed` field
      is added (23 §Stats, D256).

11. **`docs/v1/13-testing.md` §Pyramid**, the *Agent façade* row: after
    "tooling tier selection (…)" add "; continued sessions
    (`session_id=` on the fake's `sessions` key: `session/resume` when
    advertised else `session/load`, the replay discarded from the
    transcript and the counters, the `continuing session` notice, config
    options re-set, the refusal before any prompt, the provider's
    `stats()` not consulted, 23 §Testing)". §Fakes is unchanged — T088
    wrote the vocabulary.

12. **`docs/v1/15-decisions.md`.** One row, D265, `new (2026-09-12)`,
    for the choices this plan made that 23 and D254–D258 did not: (1) a
    run is continued iff `ACPAgent.session_id is not None`, an empty
    string included, and the agent's refusal is the answer to a bad id;
    (2) `client.replaying` and `client.replayed` are public attributes
    of `ACPClient` (a `client_class` subclass sees them) and every
    `session/update` received under the flag is counted, whatever its
    kind; (3) the `continuing session` notice precedes configuration,
    so it is the first chunk even when a config option is rejected; (4)
    `mcpServers` is sent as `[]` on `session/resume` as on `new`/`load`
    when the tier has no server; (5) only the agent's JSON-RPC error is
    translated to `the agent could not continue session <id>: <message>`
    — a dropped connection during the re-open is the transport failure
    a fresh run already reports; (6) `_configure` and
    `_resolve_config_id` take the options list and the id, since
    `LoadSessionResponse` and `ResumeSessionResponse` carry no
    `session_id`. Reason column: each is the boring reading of 23, and
    the alternatives (a second flag, counting only transcribed kinds, a
    notice after the configuration ones, a `resume` request with no
    `mcpServers` key) would leave a shape on the wire or in the
    transcript that depends on which method the agent happened to have.

13. **`docs/v1/17-serial-task-plan.md`.** Add the `**Status.** Done.`
    line under T089 in the same commit, naming what landed and D265, in
    the shape of T088's.

14. **`docs/v1/23-session-continuity.md`** is unchanged: it is
    normative and 05 now points at it. `docs/v1/16-implementation-
    tickets.md` has no status column; A9.2 is not edited.

15. **`docs/site/src/guide/agents.md`.** A new `## Continuing a session`
    between `## Results and exceptions` and `## Permissions and
    elicitations`: a run is one conversation and the agent forgets it
    when the process stops, unless the next run is handed the last
    result's `session_id`; a `python` fence with the two-run example
    (`first = await Reviewer(cwd=checkout).run(...)`; `again = await
    Reviewer(cwd=checkout, session_id=first.session_id).run(...)`;
    `assert again.session_id == first.session_id`) — it has to parse,
    `tests/test_docs_site.py` checks; the same `cwd`; the agent re-opens
    the session by whichever of ACP's two methods it supports (pi and
    Claude Code both persist sessions); the earlier turns are not
    written into the new attempt's transcript again — it opens with a
    `continuing session` line — and its statistics are the new turn's,
    not the whole conversation's; an agent that cannot re-open the
    session — it does not support it, the id is unknown, the `cwd`
    moved — raises `AgentError` rather than starting a fresh
    conversation, because a reply from an agent that quietly forgot
    everything would look like success. Guide register: no RFC 2119
    keywords (the site test rejects them), no citation of the design
    documents, present tense, second person as the page around it.
    Mention in `## Statistics` that on a continued run the token counts
    are the run's own turn as the agent reports them, never the whole
    session's.

16. **`skills/athanore-workflows/SKILL.md`** §The rules an agent gets
    wrong first: one bullet after "An agent submits a value…": **"To
    carry a conversation across runs, hand the last result's
    `session_id` back: `Reviewer(cwd=checkout, session_id=first.
    session_id)`, same `cwd`. It continues that session or raises
    `AgentError`; it never quietly starts a new one."** And in §Where
    to read next, the `guide-agents.md` bullet lists "continuing a
    session" among its topics. The file is 116 lines against a cap of
    150 (`tests/test_skills.py`); no fence is added, so the `from:`
    marker rule is untouched.

17. **Generated pages.** `uv run scripts/gen_docs.py` rewrites
    `docs/site/src/reference/python-api.md` (the `ACPAgent(...)`
    signature line gains `session_id: str | None = None`);
    `docs/site/src/reference/agents.md` does not change, because
    `session_id` is an instance attribute like `cwd`, not a class
    annotation — do not add a class-level annotation to make it appear.
    Then `uv run scripts/gen_skills.py` republishes `python-api.md` and
    the edited `guide/agents.md` into `skills/athanore-workflows/
    reference/` (and `python-api.md` into any other bundle that lists
    it). Run both, in that order, and commit what they wrote;
    `tests/test_docs_site.py` and `tests/test_skills.py` assert the
    bytes.

## Tests (`tests/agents/test_acp_lifecycle.py`)

A new section, `# Continuing a session (23)`, after "The transcript"
and before "The environment the child is spawned with"; the module
docstring's list of pinned facts gains a fifth bullet (a continued run
joins the session it was given or raises, and the replay is not this
attempt's transcript). Fixtures and helpers, local to the module:

- `sessions(tmp_path) -> dict[str, str]`: `{"dir": str(tmp_path /
  "sessions")}`; tests that want `resume` spread `{**sessions,
  "resume": True}`.
- `Spy(Fake)` as in `test_acp_outcomes.py` (keeps `session.process` on
  `self.process` from `_spawn`), for the `returncode` assertions. Ten
  lines, duplicated rather than moved to `conftest.py`.
- `Recording(FakeStatsProvider)`: overrides `stats` and
  `final_stop_reason` to append `("stats", session_id)` /
  `("final_stop_reason", session_id)` to `self.called` before
  delegating to `super()`. `athanore/testing/mock.py` is not changed —
  its `calls` list does not say which method was called, and the
  distinction is the assertion.
- `first_run(context, sessions, **keys) -> tuple[TaskContext, Any]`:
  runs `Fake(command=scenario(sessions=sessions, **keys), cwd=<the
  test's cwd>)` on a fresh context and returns `(ctx, result)`. Both
  runs of every test pass the same `cwd` (`str(tmp_path)`), since 23
  says they have to and the assertion on the re-open request wants a
  value to compare.

The tests, each on its own second `context()` (a second task of the
same store, so the transcripts are separate rows):

- `test_a_continued_run_loads_the_session_and_opens_no_new_one`
  (23 §Testing, façade bullet, load path). Run 1: `text=["one"],
  tool_calls=1`. Run 2: `Fake(command=scenario(sessions=…,
  text=["two"], tool_calls=2, request_log=str(logs)), cwd=…,
  session_id=first.session_id)`. Assert `methods(logs)[:2] ==
  ["initialize", "session/load"]`, `"session/new" not in
  methods(logs)`, `"session/prompt" in methods(logs)`; the load's
  params: `sessionId == first.session_id`, `cwd == str(tmp_path)`,
  `mcpServers == []`; `again.ok`; `again.session_id ==
  first.session_id`; `again.stats["session_id"] == first.session_id`;
  `again.text == "two"` (none of run 1's `one`); `again.stats
  ["tool_calls"] == 2` (not 3); `await transcript(ctx2) == [("notice",
  f"continuing session {first.session_id}"), ("text", "two"),
  ("tool_call", "fake tool 1"), ("tool_result", "completed"),
  ("tool_call", "fake tool 2"), ("tool_result", "completed")]` — exact,
  so a replayed `one` or a replayed tool call anywhere fails it (the
  ordering argument in the preamble is what this proves). Also assert
  the fake's file grew: `json.loads((sessions_dir /
  f"{sid}.json").read_text())` ends with run 2's updates — which shows
  the load really replayed run 1's before them.
- `test_the_discarded_replay_is_logged_once_at_debug`: the same two
  runs under `structlog.testing.capture_logs()`; exactly one entry with
  `event == "replay discarded"`, `log_level == "debug"`,
  `session_id == first.session_id`, and `count ==` the length of the
  session file *before* run 2 (the user chunk, `one`, the tool call
  and its update: 4 with the scenario above — compute it from the file
  rather than hard-coding).
- `test_a_continued_run_resumes_when_the_agent_can` (resume path):
  `sessions={..., "resume": True}` on both runs; run 2's `methods(logs)`
  has `"session/resume"` and neither `"session/load"` nor
  `"session/new"`; the resume's params carry `sessionId`, `cwd` and
  `mcpServers == []`; transcript is `[("notice", …), ("text", "two")]`
  exactly; `again.session_id == first.session_id`; no `replay
  discarded` log entry (under `capture_logs`).
- `test_config_options_are_set_on_the_continued_session`: run 2 with
  `config_options=VENDOR_OPTIONS`, `agent.model = "slow"`,
  `agent.thinking = "high"`; `methods(logs)` has `session/load`
  followed (not necessarily adjacently — the fake logs requests, and
  `set_config_option` is what follows) by two `session/set_config_
  option` with `[("the-model", "slow"), ("effort", "high")]` and their
  `sessionId == first.session_id`. A variant with `reject_config=
  ["the-model"]` asserts the transcript is `[("notice", "continuing
  session …"), ("notice", "model could not be set to 'slow': …"),
  ("text", …)]` — the continuing notice first (step 4's ordering).
- `test_the_mcp_tier_hands_this_tasks_server_to_the_load`: run 2 with
  `advertise_mcp=True` (no `mcp_calls`, so no server has to answer;
  `context` rather than `served_context` is enough); the load's
  `mcpServers == [{"type": "http", "name": MCP_SERVER_NAME, "url":
  f"{ctx2.api_base}/mcp/agent", "headers": [{"name": "X-Athanore-
  Token", "value": ctx2.token}]}]` — the second task's context; run 1
  did not advertise MCP, so the shape is the same as `test_tooling.py`
  asserts for `session/new`.
- `test_an_agent_that_can_do_neither_is_refused_before_any_prompt`:
  `Spy(command=scenario(text=["never"], request_log=str(logs)),
  session_id="01a0-anything")` — no `sessions` key, so the fake
  advertises neither. `pytest.raises(AgentError, match=r"Spy cannot
  continue a session: the agent advertises neither session/resume nor
  session/load")`; `methods(logs) == ["initialize"]` (no load, no
  resume, no prompt); `agent.process.returncode is not None`; `await
  stats_lines(ctx)` has one line containing `"failed (transport)"` and
  not `"session="`; the `agent.stats` event (via a local
  `events_named` as in `test_acp_outcomes.py`, or by reading the task's
  `stats` column) has `session_id` absent/`None`.
- `test_an_unknown_session_quotes_the_agents_error`: `sessions` set,
  `session_id="nope"`; `pytest.raises(AgentError, match=r"the agent
  could not continue session nope: no such session: nope")`;
  `methods(logs) == ["initialize", "session/load"]`; `returncode` set;
  one `failed (transport)` line without `session=`. Repeat for the
  resume path (`resume: True`) with `"session/resume"` in the log and
  the same message — the fake's `-32602` is the same on both.
- `test_the_provider_is_asked_for_a_stop_reason_but_not_for_stats`
  (23 §Stats, D256): a `Recording(stats={"cost": 0.25, "input_tokens":
  999}, stop_reason=None)` on run 1 → `first.stats["cost"] == 0.25`
  and `provider.called == [("final_stop_reason", sid), ("stats",
  sid)]`; a fresh `Recording(...)` on run 2 (`usage={"input": 10,
  "output": 2}` in the scenario) → `provider.called == [("final_stop_
  reason", sid)]`, `"cost" not in again.stats`, `again.stats
  ["input_tokens"] == 10`, `again.stats["output_tokens"] == 2`,
  `again.stats["model"]` is the class's `model` when one is set (set
  `agent.model = "asked-for"` on run 2 and the provider's `model` to
  `"answered-with"`; assert `"asked-for"`). A second case: run 2's
  provider with `stop_reason="length"` → `not again.ok`, `again.error
  == "truncated"` — `final_stop_reason` still decides truncation on a
  continued run.
- `test_a_replaying_client_answers_requests_and_drops_updates`, on
  `ACPClient` directly as the "What this client refuses to do" tests
  are: `client = ACPClient(Fake(command=["unused"]), None)`;
  `client.replaying = True`; `await client.session_update("s",
  AgentMessageChunk(...))` and a `ToolCallStart` → `client.text == []`,
  `client.tool_calls == 0`, `client.replayed == 2`; then `await
  client.request_permission("s", tool_call, options)` with `allow_once`
  in the options and `permission_policy = "auto_allow"` → the
  `allow_once` id is selected (the policy answered under the flag);
  `client.replaying = False` and one more `session_update` → `text`
  grows and `replayed` stays 2. Build the updates from `acp.schema`
  (`AgentMessageChunk(session_update="agent_message_chunk",
  content=TextContentBlock(type="text", text="…"))`,
  `ToolCallStart(session_update="tool_call", tool_call_id="c1",
  title="…")`) and the request from `ToolCallUpdate` and
  `PermissionOption` the way `tests/agents/test_policies.py` builds its
  `ToolCall()` and `REJECT_FIRST` helpers.
- The existing tests are untouched and stay green: in particular
  `test_the_handshake_is_initialize_new_session_prompt` still sees
  `session/new` second, which is the fresh path unchanged.
  `tests/testing/test_mock.py` and `tests/test_public_api.py` are not
  edited; the run confirms them.

No test sleeps. Two fake processes per test, each `run()` waiting on
its own child; the shared state between them is the session file
under `tmp_path`, written synchronously by the fake before it answers.

## Out of scope

- `ACPAgent.open()`, `AgentSession`, `prompt()`, the fake's `prompts`
  key — T090. Do not restructure `run()` into an entry/prompt/exit
  split here; T090 does that on top of `_open_session`.
- The `chat` seat (`workflows/chat`) — T091. It keeps pasting history
  until then.
- A fallback to `session/new`; a check of `cwd` in the façade; any
  `session/fork`, `list`, `delete`, `close`; keeping the subprocess
  alive between runs.
- A `resumed` field on the entry or the `agent.stats` payload; any
  change to `athanore/agents/stats.py`, `athanore/events/`,
  `tests/snapshots/`, `web/`.
- `athanore/testing/` (`fake_acp.py`, `mock.py`, `scenarios.py`) and
  `tests/testing/`.
- `examples/` and the live smoke tests under `tests/smoke/`: no example
  continues a session yet, and 23 §Testing asks for no smoke case.
- `docs/site/src/reference/agents.md` (unchanged by construction, step
  17) and the `docs/site/mkdocs.yml` nav (no page is added).

## Verification

```sh
./scripts/dev.sh "uv run pytest -q tests/agents/test_acp_lifecycle.py"
./scripts/dev.sh "uv run pytest -q tests/agents tests/testing tests/test_public_api.py"
./scripts/dev.sh "uv run scripts/gen_docs.py && uv run scripts/gen_skills.py"
./scripts/dev.sh "uv run pytest -q tests/test_docs_site.py tests/test_skills.py tests/test_spec_citations.py"
./scripts/test.sh
git diff --exit-code tests/snapshots web/src/api/gen
```

`ruff` (line length 88) and `pyright` standard on `athanore/agents/`;
`lint-imports` unaffected; `mkdocs build --strict` as part of the gate
for the guide edit.

## Done

- `ACPAgent(session_id=)` continues a session on `session/resume` when
  advertised, else `session/load`, else raises `AgentError` after
  `initialize` and before any prompt; both calls carry `cwd` and the
  tier's `mcp_servers`; the agent's JSON-RPC error is `AgentError` `the
  agent could not continue session <id>: <message>`; `session.
  session_id` is set only on success; the replay is discarded and
  counted under `client.replaying`, logged once at DEBUG; the attempt's
  transcript opens with `continuing session <id>`; config options are
  set on the continued session; the provider's `stats()` is not
  consulted and `final_stop_reason()` is; every failure records one
  `failed/transport` entry with no `session_id`. 05 §Agent classes,
  §The ACP client, §Session lifecycle (+ §Continuing a session) and
  §Stats entry carry the fold; 13's façade row names it; the site guide
  and the workflows skill say how; the generated reference and the
  skill copies are regenerated; D265 rowed; T089 marked Done; gate
  green; `tests/snapshots/openapi.json` and `web/src/api/gen/`
  byte-identical.

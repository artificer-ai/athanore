# T092 — The `none` tooling tier

**Task.** `docs/v1/17-serial-task-plan.md` § `### T092`.
**Specs.** `docs/v1/05-agents.md` §Agent classes (the `ACPAgent`
signature — its `tooling` literal is the one line of the section this
task changes), §Tooling tiers (the `none` row, and the two paragraphs
after the table: never picked by `auto`, the token reaches neither the
prompt nor the process, an `output_model` on the tier is a
configuration error `AgentError` names before any prompt, `text` is
what the agent returns, the repair loop never runs), §AgentResult;
`docs/v1/19-agent-prompts.md` §Prompt assembly (the sentence after the
assembly block: on `none` the task sections are omitted *exactly as
they are outside a task context*), §Environment handed to the
subprocess (neither variable is exported on `none`), §Rules (no block
changes — none is made here); `docs/v1/13-testing.md` §Fakes (the table
row for the agent façade and the scenario vocabulary; what this task
adds is below); `docs/v1/12-security.md` §Task tokens (why a token
that is never handed over is the point); `docs/v1/15-decisions.md`
D271 (the tier and its reason), D63 (the three adapters `none` is not
one of), D122 (the fake emits everything on the first turn).

This plan was written against the code as of `c454a55` (`main` after
PR #17's 05/19 edits). The state of the tree that matters:

- `athanore/agents/base.py`: `Tier = Literal["http", "mcp", "native"]`
  (line 68). `Agent.render_prompt(prompt, ctx, tier="http")` builds a
  `sections` list — system prompt, `---`, `## Your assignment`, then,
  **if `ctx is None`, logs `agent prompt rendered outside a task
  context` at WARNING and returns the join** — else appends `---`,
  the kickoff, `tier_block`, the ask block (`http` only) and the
  submission block. `tier_block(ctx, tier, *, ask)` returns
  `http_tier` for `http` and `tool_tier` for anything else. The base
  `Agent` has **no** `tooling` attribute: the tier is `render_prompt`'s
  argument and `ACPAgent.tooling` is where a class declares one, so 17's
  "if it has one, else the tier is the façade's alone" resolves to
  *the façade's alone* — nothing is added to `Agent`.
- `athanore/agents/acp.py`: `ACPAgent.tooling: Literal["auto", "mcp",
  "native", "http"] = "auto"` (line 771). `_session(whole)` is the one
  context manager behind `open()` and `run()`: it reads
  `maybe_current_task()`, builds `AthanoreSettings()`, enters
  `self.declare(ctx)`, then `_enter` (spawn, `initialize`, `session.tier
  = self._tier(initialized, ctx)`, `_open_session`, `_configure`) with a
  `_cleanup` + `_record` on failure. `_spawn` calls `_child_env(ctx)`
  **before** the handshake, so the tier `auto` negotiates is not known
  when the environment is built — which is why the environment must
  read the declaration (`self.tooling`), not `session.tier`. `_turn`
  renders `render_prompt(prompt, ctx, tier=session.tier)`, `_prompt`s,
  `_repair`s, `_outcome`s. `_repair` loops on `needs_repair(ctx,
  stop_reason)` (false without a declared `ctx.output_model`).
  `_outcome` builds the `AgentResult`, maps `refusal`/`cancelled`/
  truncation to a failed result, else `await attach(ctx, result)` —
  which reads `submissions.latest()` from the store and puts the raw
  value (or the validated model) on `result.output` — then `turn.status,
  turn.reason = "ok", None` and builds the entry. `_tier` honours the
  declaration except `mcp` with no `ctx` (falls back to `http` with a
  warning). `_mcp_servers` returns `None` unless `tier == "mcp"` and
  `ctx` is set. `_child_env` exports `ATHANORE_TASK_URL` /
  `ATHANORE_TASK_TOKEN` whenever `ctx is not None`, then merges
  `self.env` last.
- `athanore/agents/submissions.py`: `attach`, `needs_repair`,
  `repair_prompt` — **untouched** by this task; the skip lives in the
  caller, as their module docstring says it must ("neither of the last
  two decides anything").
- `athanore/testing/fake_acp.py`: **already records the environment**
  — `env_echo: true` emits one `agent_message_chunk` opening with
  `ENV_MARKER` (`[env]`) and listing `os.environ` sorted, and
  `tests/agents/test_acp_lifecycle.py` reads it back with `echoed()`.
  `request_log` records every request with its params, so
  `session/new`'s `mcpServers` and `session/prompt`'s text are already
  assertable. `select_scenario` resolves the per-node scenario from the
  kickoff line (`_KICKOFF_RE`) and falls through to `default.json`
  when the prompt has none — the path a `none` prompt takes under
  `ATHANORE_FAKE_SCENARIOS`. `post()` with neither variable set writes
  `{path: null, error: "ATHANORE_TASK_URL/TOKEN are not set"}` to
  `response_log` and a line to stderr, and returns. **The fake needs no
  change**; 17's "add the recording to the fake if it does not have
  one" is satisfied as-is.
- Tests: `render_prompt` is tested in `tests/agents/test_prompt.py`
  (17 says `test_prompts.py`; the file is `test_prompt.py`). The
  environment and the wire are `tests/agents/test_acp_lifecycle.py`
  (`Fake`, `Spy`, `logs`, `received`, `methods`, `params_of`, `run`,
  `echoed`, `stopped`; fixtures `context`, `transcript`, `stats_lines`
  from `tests/agents/conftest.py`). The tiers are `tests/agents/
  test_tooling.py`, whose `Fake` declares an `output_model` — which is
  exactly what a `none` class may not, so the new wire tests go in the
  lifecycle file as 17 says and `test_tooling.py` is not touched.
- Reference: `docs/site/src/reference/agents.md` line 29 renders
  `ACPAgent.tooling`'s literal from the class, and `scripts/gen_skills.py`
  republishes that page and `docs/site/src/guide/agents.md` into
  `skills/athanore-workflows/reference/`. `tests/test_docs_site.py` and
  CI's `contract` job assert the committed bytes are what the scripts
  write, so both scripts are run and their output committed.
- Nothing on the wire changes: `Tier` and `tooling` are Python literals
  on classes the API never serialises. `tests/snapshots/openapi.json`
  and `web/src/api/gen/` are byte-identical, and `git diff
  --exit-code` on them is part of verification.

## What this task is

A fourth value, `"none"`, on `Tier` and `ACPAgent.tooling`, and six
places that read it: the prompt (task sections omitted, no warning),
the session (no MCP server), the child's environment (no task URL or
token), the entry (`output_model` + `none` refused before anything is
spawned), the turn (no repair loop) and the outcome (no submission
lookup; `output` is `None`). No new block in 19, no new event, no new
setting, no change to any other tier's behaviour, no conversion of any
existing agent, and no auto-detection: `none` is declared or it is not
there.

Files touched, and nothing else: `athanore/agents/base.py`,
`athanore/agents/acp.py`, `tests/agents/test_prompt.py`,
`tests/agents/test_acp_lifecycle.py`, `docs/v1/05-agents.md` (one
line), `docs/v1/13-testing.md` (§Fakes), `docs/v1/15-decisions.md`
(D272), `docs/v1/17-serial-task-plan.md` (the `**Status.** Done.`
line), `docs/site/src/guide/agents.md`, and the regenerated
`docs/site/src/reference/agents.md`,
`skills/athanore-workflows/reference/agents.md`,
`skills/athanore-workflows/reference/guide-agents.md`. **Not**
`athanore/testing/fake_acp.py`, not `athanore/agents/submissions.py`,
not `tests/agents/test_tooling.py`, not `tests/test_public_api.py`,
not `workflows/`, not `examples/`.

## `athanore/agents/base.py`

### 1. `Tier`

```python
#: The ways an agent reaches its task (05 §Tooling tiers, D63) — and
#: ``none``, the declaration that it does not (D271). ``http`` is the
#: fallback and the only one this module can pick on its own; ``mcp``
#: and ``native`` are chosen by :class:`ACPAgent
#: <athanore.agents.acp.ACPAgent>` from what a session advertises, and
#: ``none`` only ever by the class.
Tier = Literal["http", "mcp", "native", "none"]
```

The module docstring's paragraph "The tiers are text here; the choice
between them is not" gains one sentence: on `none` there is no tier
block at all — the task sections are omitted as they are outside a task
context, and that is the tier's whole text.

### 2. `render_prompt`

The `none` check goes **first**, before the `ctx is None` branch, and
returns the same join that branch returns, without the warning:

```python
        if tier == "none":
            # The class said it wants nothing from its task: the task
            # sections are omitted exactly as they are outside a task
            # context, and there is nothing to warn about (19 §Assembly,
            # D271).
            return "\n\n".join(sections)

        if ctx is None:
            _log.warning(...)   # unchanged
```

So `tier="none"` with a `ctx` renders system prompt, `---`, assignment
(or the assignment alone, or the system prompt alone — the same
omission-with-separator rules as today, unchanged); `tier="none"` with
no `ctx` renders the same and logs nothing either. Every other tier is
unchanged, character for character.

The docstring's paragraph on `tier` gains: *``none`` omits the task
sections altogether — the agent is handed the system prompt and the
assignment, and nothing that names a task, a token or a tool; it is the
prompt an agent outside a task context gets, without the warning, since
here the absence was asked for (05 §Tooling tiers, D271).*

### 3. `tier_block`

`render_prompt` never reaches it on `none`, so a call with `"none"` is
a caller bug and is loud rather than a tool listing nobody asked for:

```python
    if tier == "none":
        raise ValueError("the none tier has no tier block: nothing is sent")
    if tier == "http":
        return http_tier(ctx)
    return tool_tier(ask=ask)
```

One sentence in its docstring says so. No other function in the module
changes.

### 4. `AgentResult`

The docstring's first sentence becomes: *``output`` is the validated
``output_model`` instance when the class declared one, the raw
submission when it did not, and ``None`` on the ``none`` tier, where
nothing could have been submitted (05 §Tooling tiers).* No field
changes.

## `athanore/agents/acp.py`

### 5. `tooling`

```python
    #: How this agent reaches its task (05 §Tooling tiers, D63) — or
    #: ``none``: it does not, and is given nothing to (D271).
    tooling: Literal["auto", "mcp", "native", "http", "none"] = "auto"
```

### 6. The refusal: `output_model` on `none`

At the top of `_session`, before `maybe_current_task()`, before
`AthanoreSettings()`, before `declare`:

```python
        if self.tooling == "none" and self.output_model is not None:
            raise AgentError(
                f"{type(self).__name__} declares an output_model on the none "
                "tier: it has no way to submit one"
            )
```

The message is 17's, verbatim, with the class name where 17 writes
`<Agent>`. `_session` is the body of both `open()` and `run()`, so the
exception leaves `open()`'s `__aenter__` (and `run()`) with no child
spawned, no `declare` entered, no `_Session` built and no stats entry:
`_record` is only reached from inside the `try` that this precedes.
This is the check 05 §Tooling tiers calls "before any prompt" and 17
calls "before the child is spawned, with no stats entry, because
nothing ran"; it is raised on entry rather than on the `open()` call
itself because `open()` is a plain method returning the context
manager, and every other entry failure (`_enter`'s) leaves the same
`__aenter__` — one place a body sees an `AgentError` from, not two.
`open()`'s docstring gains one sentence naming this refusal and that,
unlike the entry failures the sentence before it describes, it records
nothing.

The check reads `self.output_model` — the class attribute, or one set
on the instance, as `test_tooling.py` does with `agent.output_model =
None` — not `ctx.output_model`, which `declare` has not yet published.

### 7. `_tier`

```python
        chosen = self.tooling
        if chosen == "auto":
            ...   # unchanged: mcp when advertised, else http
        if chosen == "mcp" and ctx is None:
            ...   # unchanged: warn, fall back to http
        return chosen
```

No code change beyond the docstring: `"none"` is not `"auto"` and not
`"mcp"`, so it is returned as declared, with or without a `ctx`. The
docstring's first line becomes *Which of 05's tooling tiers this run
uses (D63, D271)* and gains: *``none`` is a declaration too, and the
only tier ``auto`` never resolves to — an agent is given nothing only
when its class says so.* Pyright must see `chosen` as `Tier` on the
return; it does today because `tooling`'s literal less `"auto"` is
`Tier`, and it still does with `"none"` on both.

### 8. `_mcp_servers`

```python
        if tier != "mcp" or ctx is None:
            return None
```

No code change: `none` is not `mcp`. The docstring gains half a
sentence: *and nothing at all on ``none``, which has no task to point
at by declaration.* `session/new` therefore carries `mcpServers: []`
on the wire, as it does for `http` and `native` (the SDK serialises
`None` as the empty list; `test_tooling.py` already asserts `[]` for
those tiers).

### 9. `_child_env`

Step 2 of the docstring's list becomes: *export ``ATHANORE_TASK_URL``
and ``ATHANORE_TASK_TOKEN``, so an adapter that reads its environment
can keep the token out of the prompt entirely (19 §Environment) —
unless the class declared ``tooling="none"``, in which case neither is
exported: the child has no use for a token and is not handed one (05
§Tooling tiers, D271);* and the code:

```python
        if ctx is not None and self.tooling != "none":
            env["ATHANORE_TASK_URL"] = task_base(ctx)
            env["ATHANORE_TASK_TOKEN"] = ctx.token
        env.update(self.env)
```

`self.tooling`, not `session.tier`: the environment is built in
`_spawn`, before the handshake that resolves `auto`, and `none` is
never the product of that handshake — it is known from the class. A
sentence in the docstring says why the declaration is read here rather
than the negotiated tier. `env.update(self.env)` still runs last and
still wins: an author who puts `ATHANORE_TASK_TOKEN` in `env=` by hand
on a `none` class gets what they wrote, as on every other tier (12
§Agents: the explicit `env` is "the one thing the workflow author
stated by hand"). Nothing in this task adds a check against that.

### 10. `_turn`

```python
                text = await self.render_prompt(prompt, ctx, tier=session.tier)
                response = await self._prompt(session, client, text, turn)
                if session.tier != "none":
                    response = await self._repair(ctx, session, client, response, turn)
                return await self._outcome(ctx, session, client, response, turn)
```

`_repair` itself is unchanged. It would return at once anyway —
`needs_repair` is false with no declared `output_model`, and §6 has
refused every `none` class that has one — but 17 says the loop is
skipped, so it is skipped rather than entered and found empty: a
`none` turn makes no `submissions.latest()` read at all. `_turn`'s
docstring, listing "the render, the turn under ``timeout``, the repair
loop and the outcome", gains *— the repair loop and the outcome's
submission lookup both skipped on ``none``, which has nothing to
repair or look up (05 §Tooling tiers)*.

### 11. `_outcome`

The `else` branch:

```python
        else:
            if session.tier != "none":
                try:
                    await attach(ctx, result)
                except AgentError:
                    turn.reason = "no_submission"
                    raise
            turn.status, turn.reason = "ok", None
```

On `none`, `result.output` stays the dataclass default `None`,
`result.text` is `"".join(client.text[turn.text_at:])` as on every
tier, `stop_reason` and `session_id` are set as today, and the entry is
built as today: `ok` with no reason on `end_turn`, and the three
failures (`refusal`, `cancelled`, truncation) are mapped **before**
this branch and unchanged — a `none` agent that refuses returns a
failed result like any other, which is what 17's "`ok` is the outcome
of the turn" means. The docstring's last paragraph becomes: *Anything
else attaches the submission, and a missing or invalid one is the
:exc:`AgentError` the body cannot route on — except on ``none``, where
there is no submission to look up: ``output`` is ``None`` and ``text``
is the answer (05 §Tooling tiers, D271).*

### 12. What is deliberately not changed

- `ask_policy="http"` on a `none` class is not refused and not warned
  about. 05 names one configuration error on the tier — `output_model`
  — and the ask block is a task section, omitted with the rest;
  `declare` still publishes `ask_policy` on the task, and the endpoint
  it enables is unreachable by an agent holding no token. Recorded in
  D272 so it is a choice, not an oversight.
- `_continue` (`session/resume` / `session/load` on a `none` class):
  `_mcp_servers` returns `None`, `or []` makes it `[]`, and the rest is
  the tier-independent path it is today. No change, no test — 23's
  continued-session tests already cover `[]` for the non-`mcp` tiers,
  and a held or continued `none` session is the same code with §10 and
  §11 applied per prompt.
- `declare(ctx)` still runs for a `none` block. It publishes
  `output_model` (necessarily `None`) and `ask_policy`; there is nothing
  tier-specific to publish and nothing to skip.
- The stats entry is ordinary: no `repair_turns` (zero is omitted),
  `tool_calls` whatever the client counted, `session_id` set. Nothing
  marks the tier.
- `athanore/agents/__init__.py` exports nothing new; `Tier` is a
  module-level name in `base.py` as today.

## Tests

### 13. `tests/agents/test_prompt.py`

Under the existing "The assembly" section, after
`test_a_task_context_is_not_warned_about`. `Everything` is the existing
class with a system prompt, `ask_policy="http"` and `output_model`
(check its definition at the top of the file and use it as-is): it is
the class with the most to omit.

- `test_the_none_tier_is_the_system_prompt_and_the_assignment(context)`:
  `ctx = await context(TITLE)`; `prompt = await
  Everything().render_prompt(ASSIGNMENT, ctx, tier="none")`; assert
  `prompt == "\n\n".join([SYSTEM, "---", f"## Your assignment\n\n
  {ASSIGNMENT}"])` — the whole text, not a substring, so a stray
  separator or a tier block would fail it; then `"## Your task" not in
  prompt`, `"curl" not in prompt`, `ctx.token not in prompt`,
  `"submit" not in prompt`, `"ask" not in prompt.lower()` are stated
  as well, because they are what 17 lists and what the equality
  implies but a reader looks for.
- `test_the_none_tier_without_a_system_prompt_is_the_assignment_alone(context)`:
  a class with no `system_prompt` and an `output_model` (define
  `class Bare(Agent): output_model = Verdict` locally or reuse an
  existing one); `render_prompt(ASSIGNMENT, ctx, tier="none") ==
  ASSIGNMENT`.
- `test_the_none_tier_is_not_warned_about(context)`: `capture_logs()`
  around a `none` render with a `ctx` → `logged == []`; and a second
  render with `ctx=None` and `tier="none"` → `logged == []` too, with a
  docstring saying why the outside-a-task warning does not fire: the
  absence was asked for.
- `test_the_none_tier_has_no_tier_block(context)`: `tier_block(ctx,
  "none", ask=False)` raises `ValueError` (import `tier_block` from
  `athanore.agents.base`).

The module docstring's opening does not change; the file's
"Everything" class and helpers are reused, not duplicated.

### 14. `tests/agents/test_acp_lifecycle.py`

A new section, `# The none tier`, placed after "The environment the
child is spawned with" (it reuses `echoed`). A local class:

```python
class Silent(Fake):
    """A façade that wants nothing from its task (05 §Tooling tiers, D271)."""

    tooling = "none"
```

and, for the refusal, `class Talkative(Spy): tooling = "none";
output_model = Verdict` — `Verdict` and `Spy` are already defined in
the file (the "Holding a session" section; `Judged` is the same shape
for the `http` tier). Place the new section after that one so both
names are in scope, or move nothing and put it at the end of the file
before the "method not found" tests; either is fine, but the section
comes after `Verdict`'s definition.

- `test_a_none_run_sends_the_prompt_alone(context, logs)`: `Silent
  (command=scenario(text=["hello"], request_log=str(logs)))`, `run(...,
  ctx, "say hello")`; the one `session/prompt`'s text is exactly
  `"You are a test agent.\n\n---\n\n## Your assignment\n\nsay hello"`
  (the `Fake` system prompt is `"You are a test agent."`); `"## Your
  task" not in text`, `ctx.token not in text`, `"curl" not in text`.
- `test_a_none_session_carries_no_mcp_server(context, logs)`: with
  `scenario(advertise_mcp=True, request_log=...)` — the agent
  *advertises* MCP and still gets none, which is what "never picked,
  only declared" costs to prove — `params_of(logs, "session/new")[0]
  ["mcpServers"] == []`.
- `test_a_none_child_gets_no_task_url_or_token(context, transcript)`:
  `scenario(env_echo=True)`; `env = echoed(await transcript(ctx))`;
  `"ATHANORE_TASK_URL" not in env` and `"ATHANORE_TASK_TOKEN" not in
  env`; and, so the test proves the scrub is the tier's and not an
  empty environment, one ordinary inherited variable (set with
  `monkeypatch.setenv("PATH_LIKE_THING", "kept")` as the scrub test
  does) is present.
- `test_a_none_result_is_the_text_with_no_output(context, stats_lines)`:
  `Spy`-style is not needed; `result = await run(Silent(command=
  scenario(text=["the", " answer"])), ctx)`; `result.ok`,
  `result.output is None`, `result.text == "the answer"`,
  `result.stop_reason == "end_turn"`, `"repair_turns" not in
  result.stats` (`build_entry` omits a zero — real data only, nothing
  zero-filled), `"reason" not in result.stats`, `result.stats["status"]
  == "ok"`, `result.stats["tool_calls"] == 0`, and `lines = await
  stats_lines(ctx)` has `len(lines) == 1` with `lines[0].startswith
  (f"[stats] node={ctx.node} attempt={ctx.attempt} ok")` (the shape
  `test_acp_outcomes.py` asserts, with `failed (…)` swapped for `ok`;
  read `athanore/agents/stats.py`'s formatter for the exact text). One
  stats entry, ordinary.
- `test_a_none_refusal_is_still_a_failed_result(context)`:
  `scenario(stop_reason="refusal", text=["no"])`; `not result.ok`,
  `result.error == "refusal"`, `result.output is None`, `result.text ==
  "no"` — 17's "`ok` is the outcome of the turn".
- `test_a_none_class_with_an_output_model_is_refused_before_any_child
  (context, stats_lines)`: `agent = Talkative(command=scenario(text=
  ["never"]))`; `with pytest.raises
  (AgentError, match="declares an output_model on the none tier")`,
  inside `bind(ctx)`, `async with agent.open(): entered = True`; assert
  `not entered`, `agent.process is None` (never spawned, so `returncode`
  was never set — the assertion 17 asks for, stated as the process
  never existing), and `await stats_lines(ctx) == []`. A second
  assertion in the same test: `run()` raises the same (`with
  pytest.raises(AgentError, match=...): await run(agent, ctx)`), still
  `agent.process is None`, still no entry.
- `test_a_none_run_outside_a_task_is_the_same_prompt(logs)`: no
  `ctx`, no `bind`: `await Silent(command=scenario(text=["hi"],
  request_log=str(logs))).run("say hi")` → the prompt text is the
  same shape as with a task, `mcpServers == []`, `result.output is
  None`. (This is the path `_tier` returns `none` on with `ctx is
  None`, and the one where the old code would have warned.)

Update the file's module docstring bullet on the environment — *"and
the task token and URL are exported"* — to add *"— except on the
``none`` tier, which is given neither (D271)"*, and its closing
paragraph's pointer to `test_tooling.py` stands (the `none` wire tests
are here because `test_tooling.py`'s `Fake` declares an
`output_model`).

### 15. Untouched tests that must stay green

`tests/test_public_api.py` (unchanged, as 17 says — nothing it lists
changes), `tests/agents/test_tooling.py`, `tests/agents/
test_acp_outcomes.py`, `examples/tests/test_pi_agent.py` and
`test_adapters.py` (they assert `ACPAgent.tooling == "auto"` and the
adapters' own values; the literal's fourth member changes none of
them), `tests/test_docs_site.py` (green only after §17's regeneration).

## Documents

### 16. `docs/v1/`

- `05-agents.md` §Agent classes, line 26: `tooling: Literal["auto",
  "mcp", "native", "http", "none"] = "auto"   # how the agent reaches
  its task, or "none" (§Tooling tiers)`. §Tooling tiers is already
  complete (the row, and the paragraph after the table) and is not
  edited.
- `13-testing.md` §Fakes: the *Agent façade* row of the table gains,
  after the tooling-tier-selection clause, `; the none tier (no task
  section in the prompt, no mcpServers, no ATHANORE_TASK_URL/TOKEN in
  the env_echo, output None, an output_model refused before any child,
  D271)`. And one bullet after "A scenario scripts **one run**", the
  paragraph 17 asks for — what a `none` run looks like on the fake:
  *A run on the `none` tier needs nothing new from the fake and looks
  like this on it: `session/new` carries `mcpServers: []`; the prompt
  has no `## Your task`, so under `ATHANORE_FAKE_SCENARIOS` it resolves
  to `default.json` (the kickoff line is what names the node); an
  `env_echo` listing has neither `ATHANORE_TASK_URL` nor
  `ATHANORE_TASK_TOKEN`; and a `log` or `submit` key in its script
  cannot post — the fake writes `ATHANORE_TASK_URL/TOKEN are not set`
  to `response_log` and stderr and the run goes on — so a `none`
  scenario scripts `text` and nothing that needs a task. `AgentResult.
  output` is `None` and `.text` is the scripted text (05 §Tooling
  tiers, D271).*
- `15-decisions.md`: one row, **D272**, status `new (2026-09-13)`:
  *`none`-tier mechanics settled by T092: the `output_model` refusal is
  raised on entry of `open()`/`run()` (the one `__aenter__` every entry
  failure leaves), before the task is read, settings built, the agent
  declared or a child spawned, and records no entry; `_child_env` reads
  the class's `tooling` rather than the negotiated tier, since the
  environment is built before the handshake and `none` is never
  negotiated; the repair loop and the submission lookup are skipped
  rather than entered-and-empty, so a `none` turn reads no submission;
  `ask_policy="http"` on a `none` class is neither refused nor warned
  about — 05 names one configuration error on the tier, and the ask
  block is a task section omitted with the rest; `tier_block("none")`
  raises `ValueError` as a caller bug.* Reason: *each is the boring
  reading of 05 §Tooling tiers and 17 §T092; written down so the
  refusal's timing and the env's source are not re-derived.*
- `17-serial-task-plan.md`: `**Status.** Done.` under `### T092`, in
  the same commit, in the shape of the T090/T091 lines (what landed,
  in one or two sentences — the four members of `Tier`, the refusal in
  `_session`, the two skips, D272).

### 17. `docs/site/`, `skills/`

- `docs/site/src/guide/agents.md`, the tooling section: the list gains
  a fourth bullet after **HTTP** — *- **None**, when the agent has no
  business with its task at all. Set `tooling="none"` on the class.* —
  and the paragraph after `tooling="auto"` is followed by a new one, the
  paragraph 17 asks for: when to give an agent no task API. Three or
  four sentences, narrative, no rule restated (D214): an agent whose
  only job is to talk — a chat turn, a summariser, a classifier — gets
  the system prompt and the assignment and nothing else: no tool
  listing, no request lines, no server on the session, no task token
  in its environment; what it says comes back as `result.text` and
  `result.output` is `None`; a class that sets `tooling="none"` and an
  `output_model` is refused with `AgentError` when it is opened, since
  it asked for a value from an agent it gave no way to deliver one;
  `auto` never picks it — say so, and say why an agent handed a tool
  listing tends to use it (D271's reason, in the site's voice).
- Regenerate: `uv run scripts/gen_docs.py && uv run
  scripts/gen_skills.py`. Expected diff: `docs/site/src/reference/
  agents.md` and `skills/athanore-workflows/reference/agents.md` line 29
  (the literal); `skills/athanore-workflows/reference/guide-agents.md`
  (the guide, republished). Nothing else should move; if it does, the
  scripts found something this plan did not, and the implementer says
  what.

## Verification

In the container (`./scripts/dev.sh`), in this order while iterating:

```sh
uv run pytest -q tests/agents/test_prompt.py tests/agents/test_acp_lifecycle.py
uv run pytest -q tests/agents tests/test_public_api.py examples/tests
uv run ruff check . && uv run ruff format --check .
uv run pyright
uv run lint-imports
uv run scripts/gen_docs.py && uv run scripts/gen_skills.py
uv run scripts/dump_openapi.py && pnpm -C web gen
git diff --exit-code tests/snapshots web/src/api/gen      # byte-identical
uv run mkdocs build --strict -f docs/site/mkdocs.yml
```

then `./scripts/test.sh` whole, then the PR's CI. `git diff --stat`
before committing names exactly the files of §"What this task is" and
no others.

## Exit condition

17 §T092 **Done**: an agent class can say it needs nothing from its
task, and then gets nothing — no block, no tool, no token; a `none`
class answers in one turn on the fake with no tool calls, `output`
`None` and `text` the reply; a `none` class with an `output_model` is
refused from `open()` with no child and no entry; 05 (the signature),
13 (§Fakes) and 19 (already) say so; the reference and the skills are
regenerated; `tests/snapshots/openapi.json` and `web/src/api/gen/` are
byte-identical; gate green; one commit, `T092: the none tooling tier`,
with the `**Status.** Done.` line and D272 in it.

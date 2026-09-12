# 23 — Session continuity: one ACP session across several agent runs

The third post-1.0 feature set. Today every `ACPAgent.run()` is a whole
conversation: spawn the adapter, `initialize`, `session/new`, prompt,
repair, stop (05 §Session lifecycle). That is the right shape for a
pipeline stage, where the prompt is the assignment and the session is
disposable once the value is submitted. It is the wrong shape for a
body that talks to the same agent turn after turn — a chat, a reviewer
that is asked a follow-up, a builder resumed after a `human_input` —
because each turn begins with an agent that remembers nothing, and the
body has to paste the conversation back into the prompt to fake the
memory it threw away.

ACP has the two operations this needs. `session/load` re-opens a
session the agent persisted and **replays** its history to the client
as `session/update` notifications before it answers; `session/resume`
re-opens one **without** the replay. Both take the same `cwd` and
`mcpServers` a `session/new` takes, and both advertise themselves on
`initialize` (`agentCapabilities.loadSession`;
`agentCapabilities.sessionCapabilities.resume`). Verified 2026-09-11
against the sandbox's adapters: `pi-acp` 0.0.33 advertises `load` and
not `resume`; `@agentclientprotocol/claude-agent-acp` 0.75.1 advertises
both. The SDK (`agent-client-protocol` 0.12.1) carries both methods on
`ClientSideConnection`. Nothing here needs an unstable protocol
feature.

This document gives the façade one argument, `session_id=`, and says
exactly what a run does with it. [`05-agents.md`](05-agents.md) and
[`13-testing.md`](13-testing.md) remain the specs for the façade and
the fake; this document is normative for the behaviour it adds, and
the tasks that build it (T088, T089) fold the deltas back into those
documents' affected sections, each pointing here. Where this document
and one of them disagree afterwards, that is a bug in the fold, not a
choice.

## Why

The `chat` seat under `workflows/` is the proof. Its docstring says
what it does today: every turn is a fresh ACP session, and the agent's
memory is the last twenty turns of the transcript pasted into the
assignment. That is honest and it works, and it is slow and it gets
worse with every turn — the prompt grows, the model re-reads it, and
the agent re-discovers the checkout each time. With a session held
across turns the prompt is the message, the agent's context is the
agent's own, and a turn costs a turn.

Nothing about this is specific to a chat. Any body that runs the same
agent more than once on one problem — the repair-then-re-review
shape, the builder that waits on a person mid-task and picks up where
it left off — has the same choice today between re-explaining and
forgetting.

## Scope

In scope: `session_id=` on `ACPAgent`; the façade choosing
`session/resume`, `session/load` or a refusal from what the agent
advertises; the replay of a loaded session kept out of the transcript
and the counters; the stats entry told the truth on a continued
session; the fake persisting sessions across processes so the whole of
it is testable in CI.

Out of scope, explicitly:

- **Keeping the subprocess alive between runs.** A run still spawns
  the adapter and stops it (05 §Session lifecycle step 7). The session
  persists because the *agent* persists it — pi to its session files,
  Claude Code to its project directory — and the next run re-opens it.
  A long-lived adapter process held across `run()` calls would change
  what a `TaskContext` owns, what cancellation kills and what a pool
  slot means, and none of that is asked for here (D254).
- **Forking, listing, deleting or closing sessions.** ACP has
  `session/fork` (unstable), `session/list`, `session/delete` and
  `session/close`; none is a seam a body has asked for. `session_id`
  in and `session_id` out is the whole surface.
- **A prompt that knows it is continuing.** The assembly of 19 is
  unchanged: `system_prompt`, the assignment, the task block, the tier
  block. A body that wants a shorter prompt on the second turn writes
  a shorter assignment; the façade does not edit the text it is given
  (19 is byte-exact and the fake parses it).
- **Falling back to a new session.** A run asked to continue a session
  either continues it or raises. See §Refusal.
- **The engine, the store, the wire.** Nothing here reaches past the
  façade. `tests/snapshots/openapi.json` and `web/src/api/gen/` are
  byte-identical throughout the phase; the `agent.stats` payload of 18
  gains no field (D256).

## Terms

- **A continued run**: a `run()` on an `ACPAgent` constructed with
  `session_id=`. Its counterpart is a **fresh run**, today's behaviour.
- **The replay**: the `session/update` notifications an agent sends
  between receiving `session/load` and answering it. They describe
  turns that already happened, in an earlier run, in an earlier
  attempt's transcript.
- **The continued attempt**: the task attempt the continued run belongs
  to. Its transcript is its own; the earlier turns belong to the
  attempts that produced them.

## Surface

```python
class ACPAgent(Agent):
    def __init__(self, command=None, cwd=None, timeout=None, env=None,
                 session_id: str | None = None): ...
```

`session_id` is an argument of construction, beside `cwd`, `timeout`
and `env`, because it is per-instance configuration of the same kind:
*where* and *how* this run happens, not *what* it is asked (D254). It
is not a class attribute — no class continues one session — and it is
not a `run()` parameter, because `Agent.run(prompt)` is the signature
every double implements and a session is a thing only the ACP façade
has.

`AgentResult.session_id` is unchanged and is where the id comes from:

```python
first = await Reviewer(cwd=checkout).run(assignment)
again = await Reviewer(cwd=checkout, session_id=first.session_id).run(follow_up)
assert again.session_id == first.session_id
```

The `cwd` MUST be the one the session was opened with. ACP says so
(`cwd` "must match the session's"), and it is the agent that enforces
it; the façade passes what it was given and reports the agent's
refusal (§Refusal).

## Lifecycle of a continued run

05 §Session lifecycle, with step 2 replaced. The other steps are
unchanged and are listed only where a continued run is different.

1. Spawn, exactly as a fresh run: the same command, the same scrubbed
   environment, the task's `ATHANORE_TASK_URL` / `ATHANORE_TASK_TOKEN`
   exported — **this** task's, not the one the session was opened
   under. Tokens are per task (12 §Task tokens); a continued session is
   not a continued token.
2. `initialize`, then choose, from what the agent advertised, in this
   order:
   - `agentCapabilities.sessionCapabilities.resume` present →
     `session/resume` with `session_id`, `cwd` (`self.cwd or
     os.getcwd()`) and the same `mcp_servers` a `session/new` would
     carry for this run's tier (05 §Tooling tiers). No replay follows.
   - else `agentCapabilities.loadSession` true → `session/load` with
     the same arguments. The agent replays the history, then answers.
   - else → refuse (§Refusal). The child is stopped; nothing is
     prompted.

   `resume` first because it is the cheaper of the two on the wire and
   the replay is something this façade has to discard; `load` is the
   one every adapter that persists sessions has (D255).

   The response's `configOptions` is configured exactly as a
   `session/new` response is: `model` and `thinking` resolved by
   category and set, a rejected option logged and never swallowed (05
   §Agent classes). A continued session is re-told what the class
   asks for, because the class is the configuration and a session that
   drifted from it — an operator changed the model mid-conversation in
   another client — is not the one the workflow author declared.

   `session.session_id` is set to the requested id when the load or
   resume **succeeds**, not before: a run that failed to join a
   session did not have one, and its stats entry MUST NOT name it.
3. The continued attempt's transcript opens with one `notice` chunk,
   `continuing session <session_id>`, written by the façade before the
   prompt (05 §The ACP client: façade notices are `notice`). It is the
   one line that tells a reader why this attempt's transcript starts
   in the middle of a conversation, and it is written on both paths so
   the transcript does not depend on which method the agent had
   (D258).
4. Prompt, repair, outcome: unchanged. The repair loop already runs on
   "the same session" (05 step 5); on a continued run that is the
   continued session.
5. Cleanup and accounting: unchanged in mechanism (05 step 7). The
   entry's content on a continued run is §Stats.

### The replay is not this attempt's transcript

Between sending `session/load` and receiving its response, the client
is **replaying**, and while it is:

- `session_update` writes nothing to the transcript;
- assistant text is not appended to what becomes
  `AgentResult.text`;
- `ToolCallStart` is not counted towards `tool_calls`;
- a `request_permission` or `create_elicitation` is answered as it
  would be outside a replay — a replay is history and gives an agent
  nothing to ask about, but a façade that dropped such a request on
  the floor would hang the adapter waiting for an answer that never
  comes. The policy's answer is the honest one either way.

The replaying flag is set by the run around the `session/load` call
and cleared when the call returns, on every path; `session/resume`
never sets it, because nothing is replayed. The updates dropped are
counted and logged once at DEBUG (`replay discarded`, with the count),
so a transcript that looks too short has a line saying why.

Why discard rather than record: the replayed turns already have a
transcript, on the attempt that ran them, and a work log that quotes
them. Recording them again on every continued attempt would make a
ten-turn chat's tenth transcript carry the first nine, and its stats
count tool calls it did not make. A `StreamChunk` belongs to the
task that produced it (03 §StreamChunk), and a replay produced
nothing.

### Refusal

A continued run raises `AgentError` and returns nothing when:

- the agent advertises neither `sessionCapabilities.resume` nor
  `loadSession` — message `<Agent> cannot continue a session: the agent
  advertises neither session/resume nor session/load`, raised after
  `initialize` and before any prompt; the child is stopped;
- the agent answers `session/load` or `session/resume` with a JSON-RPC
  error — an unknown id, a `cwd` that is not the session's, a session
  it can no longer read — message `the agent could not continue session
  <id>: <the agent's message>`;
- anything a fresh run would already raise for.

All of them record a stats entry with `status=failed` and
`reason=transport`, the reason 05 §Stats entry gives every failure
that is the conversation not happening rather than the model
declining. No new reason is added: a body that catches `AgentError`
reads the message, and a stats reader sees a run that never got to a
prompt. The entry does not carry `session_id` (§Lifecycle step 2).

There is deliberately **no fallback** to `session/new`. A body that
asked for a session it cannot have is misconfigured — the wrong
adapter, a session file deleted, a `cwd` that moved — and a run that
quietly started over would answer its assignment with no memory of
the conversation and report success. That is the failure mode this
whole document exists to remove, and the precedent is 05 §Policies:
`auto_allow` raises when neither allow kind is offered rather than
picking something else (D254).

## Stats

The entry of 05 §Stats entry, with one thing left out on a continued
run and nothing added:

- **The provider's `stats()` is not consulted.** A `SessionStatsProvider`
  reports a *session* — `examples/pi/stats.py` sums every assistant
  message in the session file — and a continued run is a fraction of
  one whose size the provider cannot know. Attributing the whole
  session's tokens and cost to the tenth turn would be the estimate
  01 §Design principles (real data only) forbids, so on a continued
  run `input_tokens`, `output_tokens`, `total_tokens` and `cost` come
  from ACP's per-turn `usage` (05 §Truncation detection is a provider
  concern) or are omitted (D256).
- **`final_stop_reason()` is still consulted.** The final turn of the
  session is this run's final turn, and truncation is decided the
  same way on both paths.
- `session_id` is the continued session's, so the entries of every
  run on one session carry the same id — which is how an operator
  reads a conversation's cost across its `[stats]` lines, and why no
  `resumed` field is added: it would be a wire change (18's
  `agent.stats` row) to say what the ids already say.
- `model`: the provider's answer is not read (above), so it is the
  class's configured `model`, as on any run without a provider.

## The fake

`FakeACPAgent` (13 §Fakes) has to persist a session across two
processes, because a continued run is a second process. One scenario
key:

- `sessions: {dir, resume?: bool}` — the fake advertises
  `loadSession: true` on `initialize`, and `sessionCapabilities.
  resume: {}` too when `resume` is true. `session/new` creates
  `<dir>/<sessionId>.json`; the file is **the ordered list of every
  `session/update` the session has sent**, plus one
  `user_message_chunk` update per `session/prompt` received (the
  prompt's text blocks concatenated), appended as they happen.
  `session/load` with a known id re-sends every recorded update
  verbatim, in order, then answers `{configOptions}` (the scenario's,
  as `session/new` would) and carries on recording under the same id;
  `session/resume` answers without re-sending anything, and only when
  `resume` was advertised — otherwise it is `method not found`, as any
  unadvertised method is. Both record `mcpServers` as `session/new`
  does, so `mcp_calls` works on a continued session. An id with no
  file is a JSON-RPC error `-32602`, `no such session: <id>`. Without
  the key, `initialize` advertises `loadSession: false` and no
  `sessionCapabilities`, as today, and `session/load` is `method not
  found`.

Everything else about the fake is unchanged. In particular a scenario
still scripts one **run** (D122): the second process runs its first
turn's script again, which is what a test wants — the continued run's
content is the continued run's scenario. The recorded file is the
fake's own contract, not pi's layout; `session_file` keeps writing
that.

## Testing

Per 13 §Pyramid, at the lowest layer that expresses each behaviour:

- **Fake** (`tests/testing/test_fake_acp.py`, against a raw ACP
  client): `sessions` advertises `loadSession` and, with `resume`,
  `sessionCapabilities.resume`; a session's file grows by the updates
  the turn sent plus the `user_message_chunk`; a second process's
  `session/load` re-sends exactly the file's updates before its
  response and its later turn appends to the same file;
  `session/resume` sends nothing before its response; an unknown id is
  `-32602`; `session/resume` unadvertised is `-32601`; `mcpServers` on
  `session/load` is recorded; without the key `session/load` is
  `-32601`.
- **Façade** (`tests/agents/test_acp_lifecycle.py`, on the fake): a
  fresh run's `session_id` handed to a second agent continues it —
  `session/load` in the fake's `request_log`, no `session/new`,
  `mcpServers` and `cwd` on it; the second attempt's transcript is the
  `notice` then the second turn's chunks and none of the first's;
  `AgentResult.text` and the entry's `tool_calls` are the second
  turn's; the result's and the entry's `session_id` equal the first's.
  With `resume` advertised: `session/resume` and no `session/load`.
  Config options are set on the continued session (`session/set_
  config_option` follows the load). `AgentError` on an agent
  advertising neither, after `initialize` and before any prompt, the
  child stopped (`returncode` set), the entry `failed/transport` with
  no `session_id`; `AgentError` on an unknown id with the agent's
  message quoted. Stats: a `FakeStatsProvider` whose `stats()` records
  its calls is not called on the continued run and is on the fresh one;
  its `final_stop_reason` is called on both; ACP `usage` on the
  continued turn lands in the entry. `MockAgent` and `StatsMockAgent`
  are untouched and their tests prove it.
- **Public API** (`tests/test_public_api.py`): `ACPAgent` still exports
  under both names; the signature test, if one exists, gains the
  argument.

`tests/snapshots/openapi.json` and `web/src/api/gen/` do not change in
either task of this phase.

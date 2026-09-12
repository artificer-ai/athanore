# T088 — `FakeACPAgent`: sessions that survive the process

**Task.** `docs/v1/17-serial-task-plan.md` § `### T088`.
**Specs.** `docs/v1/23-session-continuity.md` §The fake (normative for
everything here), §Testing (the **Fake** bullet only — the façade and
public-API bullets are T089's), §Scope (what is out), §Terms;
`docs/v1/13-testing.md` §Fakes (the vocabulary sentence and the
"one run, one script" bullet); `docs/v1/05-agents.md` §Session
lifecycle (what a `session/new` carries, so `load`/`resume` take the
same); D122 (a scenario scripts one run; `initialize` and `session/new`
are answered from `default.json` under `ATHANORE_FAKE_SCENARIOS`);
D257 (the file is the verbatim ordered list of updates sent plus one
`user_message_chunk` per prompt); D255 (why `resume` is opt-in: the
façade of T089 prefers it, and the suite has to exercise both paths).

This plan was written against the code as of `65f95d1`: the fake is a
980-line stdlib-only script, every notification it sends goes through
`FakeACPAgent.update()`, `session/new` is `new_session()`, and
`dispatch()` answers anything else with `-32601`. The raw client in
`tests/testing/test_fake_acp.py` (`RawACPClient`) already records every
notification in arrival order and already proves `session/load` is
`-32601` today (`test_an_unknown_method_is_a_json_rpc_error`).

## What this task is

The fake learns to persist a session to disk and re-open it in a
second process, because T089's continued run *is* a second process
(23 §Scope: the subprocess is not kept alive). One scenario key,
`sessions: {dir, resume?: bool}`, turns it on. With it, the fake
advertises `loadSession` (and `sessionCapabilities.resume` on
request), writes `<dir>/<sessionId>.json` as the ordered list of what
the session sent, and answers `session/load` by re-sending that list
and `session/resume` by sending nothing. Nothing else about the fake
changes: the scenario still scripts one run, the first-turn script
still runs on the second process's first prompt (D122), `session_file`
still writes pi's layout at startup with the process's own id.

Nothing outside `athanore/testing/`, `tests/testing/` and the three
documents named below is touched. `athanore/agents/acp.py` is T089.
`tests/snapshots/openapi.json` and `web/src/api/gen/` are not
regenerated and `git diff --exit-code` on them is part of verification.

## The fake (`athanore/testing/fake_acp.py`)

1. **Vocabulary.** Add `"sessions"` to `SCENARIO_KEYS`. Add
   `_validate_sessions(value, where)` beside `_validate_session_file`,
   called from `validate_scenario`:
   `_fields(value, {"dir", "resume"}, {"dir"}, f"{where}.sessions")`;
   `dir` must be a `str` (`expected a string`), `resume` when present a
   `bool` (`expected true or false`). Nothing else is accepted — the
   same loudness as every other key, so `scenario(sessions={"dir": d,
   "replay": True})` fails at the call site naming the key.

2. **State on the instance**, set in `__init__`:
   `self.session_path: str | None = None` (the file this process is
   recording to; `None` until a session is opened) and
   `self.history: list[dict[str, Any]] = []` (the file's content, in
   memory). The `sessions` spec itself is read from `self.scenario`
   when `initialize`, `session/new`, `session/load` or `session/resume`
   is answered — under `ATHANORE_FAKE_SCENARIOS` that is `default.json`,
   exactly as `advertise_mcp` and `config_options` are read (D122 (4)).
   Recording state lives on the instance and not in `self.scenario`
   because `select_scenario()` **replaces** `self.scenario` on the first
   prompt in directory mode, and a swap must not stop the recording
   mid-session.

3. **`initialize`.**
   ```python
   sessions = self.scenario.get("sessions")
   capabilities = {
       "loadSession": sessions is not None,
       "promptCapabilities": {},
       "mcpCapabilities": {"http": advertised, "sse": False},
   }
   if sessions is not None and sessions.get("resume"):
       capabilities["sessionCapabilities"] = {"resume": {}}
   ```
   Without the key the result is byte-identical to today's
   (`loadSession: False`, no `sessionCapabilities`). With the key and
   no `resume`, `loadSession: true` and still no `sessionCapabilities`
   — 17 says "when `resume`", and an empty `sessionCapabilities: {}`
   would be a capability object advertising nothing. `SessionResumeCapabilities`
   in the SDK (`acp/schema.py`) is an empty object, so `{}` is the
   right value.

4. **Opening a session, once.** Pull the body of `new_session()` into
   `_open(params) -> None`: sets `self.mcp_servers` from
   `params["mcpServers"]` (the same list comprehension as today) and
   `self.config` from the scenario's `config_options` /
   `DEFAULT_CONFIG_OPTIONS`. `new_session()` calls `_open`, then — when
   `sessions` is in the scenario — calls `_start_recording(sessions)`,
   which does `os.makedirs(dir, exist_ok=True)`, sets
   `self.session_path = os.path.join(dir, f"{self.session_id}.json")`,
   sets `self.history = []` and writes the file (`_flush`). The file
   therefore exists as `[]` from `session/new` on, so a `session/load`
   that follows a `session/new` with no prompt in between is a known
   id that replays nothing. `new_session()` returns `{"sessionId",
   "configOptions"}` as today.

5. **Recording.** `update()` gains one line after `send()`: if
   `self.session_path is not None`, `_record(update)`. `_record`
   appends `dict(update)` — the **`update` object** of the
   notification's params, the thing carrying `sessionUpdate` — to
   `self.history` and calls `_flush`, which rewrites the whole file as
   `json.dumps(self.history)` (a JSON list, `"w"` mode, one write). The
   envelope (`jsonrpc`, `method`, `params.sessionId`) is not recorded:
   the id is the file's name and the method is always `session/update`,
   so the list of update objects *is* the verbatim record and reads as
   one. **Decision** (for 15): the file holds update objects, not
   notification envelopes; and it is rewritten in full on each append
   rather than patched, because the in-memory list is the truth and a
   session in CI is a few dozen entries. `_flush` writes to
   `<path>.tmp` then `os.replace` onto `<path>`, so a reader in another
   process never sees a half-written list.

   Only `update()` records. `request()` (permissions, elicitations)
   sends agent-initiated *requests*, which are not `session/update`
   and are not part of what ACP replays; nothing changes there. The
   `[env]` echo, thoughts, tool calls and `mcp_calls` results all go
   through `update()`/`chunk()` already, so they are recorded with no
   further hook.

6. **The prompt's user chunk.** First thing in `prompt()`, once `text`
   is concatenated and before scenario selection, sleep, and the turn's
   script: if `self.session_path is not None`, `_record({"sessionUpdate":
   "user_message_chunk", "content": {"type": "text", "text": text}})`.
   It is **recorded, not sent**: a live turn does not echo the user's
   message back (no real adapter does), but a replay carries it, which
   is exactly what pi's and Claude's `session/load` do and what T089's
   "replay is not this attempt's transcript" has to discard. `text` is
   the concatenation of the prompt's text blocks that `prompt()`
   already computes; non-text blocks contribute nothing, as today.

7. **`session/load`.** In `dispatch`, before the `-32601` fallthrough:
   ```python
   elif method in ("session/load", "session/resume"):
       self.load_session(request_id, method, params)
   ```
   `load_session(request_id, method, params)`, with `replay = method ==
   "session/load"`:
   - `sessions = self.scenario.get("sessions")`; if `None` →
     `self.fail(request_id, -32601, f"method not found: {method}")`
     (the same message the fallthrough produces, so a client cannot
     tell the two apart — it is the same fact).
   - if not `replay` and not `sessions.get("resume")` → `-32601`
     likewise: an unadvertised method is not found.
   - `session_id = params.get("sessionId")`; not a `str` → `-32602`
     `sessionId: expected a string`.
   - `path = os.path.join(sessions["dir"], f"{session_id}.json")`; no
     file → `-32602` `no such session: <session_id>` (the exact text 23
     §The fake and 17 give; T089 quotes the agent's message).
   - read the file; not a JSON list → `-32603` `session <path>: not a
     JSON list` (**decision**: a corrupt file is an internal error, not
     a wrong argument, and it is reported rather than treated as
     unknown).
   - `self.session_id = session_id`, `self.session_path = path`,
     `self.history = the list read` — adopted **before** any replay so
     the re-sent notifications carry the loaded id.
   - `self._open(params)` — `mcpServers` recorded and `configOptions`
     rebuilt exactly as `session/new` does (17: "records `mcpServers`
     as `session/new` does"), so `mcp_calls` on the continued run's
     first turn connects to the server `session/load` carried.
   - if `replay`: for each `entry` in `self.history`, `self.send({...
     "method": "session/update", "params": {"sessionId":
     self.session_id, "update": entry}})` — **directly through
     `send()`, never `update()`**, or the replay would append itself to
     the file it is replaying.
   - `self.reply(request_id, {"configOptions": self.config})`.
     `LoadSessionResponse` and `ResumeSessionResponse` in the SDK both
     take `configOptions` and an optional `modes`; the fake sends
     `configOptions` only, as `session/new` does.

   `self.turn` is untouched by a load, so the second process's first
   prompt is turn 0 and runs the scenario's first-turn script (D122,
   23 §The fake's last paragraph). `cwd` on the request is not checked
   (**decision**: the fake does not record a `cwd` and 23 gives that
   enforcement to real agents; T089 tests the refusal path through an
   unknown id, which is the error the fake does produce).
   `additionalDirectories` and `_meta` are ignored as they are on
   `session/new`.

8. **`request_log`** needs nothing: `run()` already logs every
   received request's `method` and `params` before dispatch, which is
   how T089 will assert `session/load` with `cwd` and `mcpServers` and
   no `session/new`.

9. **The module docstring.** Add one paragraph after "**One run, one
   script.**": the `sessions` key, the file (`<dir>/<sessionId>.json`,
   a JSON list of update objects, one `user_message_chunk` recorded per
   prompt and every update sent, in order), `session/load` re-sends it
   and `session/resume` does not, the `-32602`/`-32601` cases, and
   that the first-turn script still runs in the second process. Point
   at 23 §The fake and D257. The `SCENARIO_KEYS` comment stays "The
   whole scenario vocabulary of 13 §Fakes" — 13 is where the sentence
   lives after the fold.

## Documents

10. **`docs/v1/13-testing.md` §Fakes.** In the vocabulary sentence,
    after the `mcp_calls` entry and before "Unknown keys are an error",
    add: `sessions: {dir, resume?: bool}` (advertises `loadSession` on
    `initialize`, and `sessionCapabilities.resume` when `resume`;
    `session/new` writes `<dir>/<sessionId>.json`, the ordered list of
    every `session/update` sent plus one `user_message_chunk` per
    prompt received; `session/load` re-sends it verbatim before
    answering `{configOptions}`, `session/resume` answers without a
    replay and only when advertised; both record `mcpServers` as
    `session/new` does; an unknown id is `-32602` `no such session:
    <id>`, an unadvertised method `-32601`; the fake persists a session
    across two processes, 23 §The fake, D257). Extend the "one run"
    bullet with one sentence: the second process of a continued
    session runs the first-turn script again on its first prompt (23
    §The fake). Keep the sentence's existing shape and density; it is
    the contract, and the site does not republish it.

11. **`docs/v1/15-decisions.md`.** One row, D259, `new (2026-09-12)`,
    for the choices this plan made that 23/D257 did not: the file
    holds update objects (not envelopes) and is rewritten atomically in
    full per append; the `user_message_chunk` is recorded and not sent
    on the live turn; `cwd` is not checked; a corrupt file is `-32603`;
    the `sessions` key is read when `initialize`/`session/new`/`load`
    is answered (so `default.json` under `ATHANORE_FAKE_SCENARIOS`) and
    the recording state is held on the instance so a per-node scenario
    swap does not stop it. Reason column: each is the boring reading of
    23 §The fake, and the alternatives (recording envelopes, echoing
    the user chunk live, inventing a cwd check) would put a shape in
    the file or on the wire that no real adapter produces.

12. **`docs/v1/17-serial-task-plan.md`.** Add the `**Status.** Done.`
    line under T088 in the same commit, naming what landed and D259.

13. **`docs/v1/23-session-continuity.md`** is unchanged. It is
    normative and already says everything §The fake needs; the fold is
    13 gaining the sentence and pointing back (step 10).

## Tests (`tests/testing/test_fake_acp.py`)

Against `RawACPClient`, in a new section "Sessions across processes"
before "Per-node selection, and the errors". Extend the client with
`initialize()` (the `initialize` call alone, returning its result),
`load(session_id, **params)` and `resume(session_id, **params)` —
each sends the method with `{"sessionId", "cwd": os.getcwd(),
"mcpServers": [], **params}` through `call()`, sets
`self.session_id`, and returns the result — so a second process can
open without `session/new`. A module-level `read_session(dir,
session_id) -> list` reads the file.

- `test_sessions_advertises_load_session_and_resume_on_request`:
  `scenario(sessions={"dir": d})` → `loadSession is True` and
  `"sessionCapabilities" not in agentCapabilities`;
  `scenario(sessions={"dir": d, "resume": True})` →
  `sessionCapabilities == {"resume": {}}`; `scenario()` → `loadSession
  is False` and no `sessionCapabilities` (the existing handshake test
  does not assert this; add it here so "as today" is proven).
- `test_session_new_creates_the_file_and_a_turn_fills_it_in_order`:
  `scenario(sessions=…, thoughts=["hmm"], text=["one", "two"],
  tool_calls=1)`; after `handshake()` the file exists and is `[]`;
  after `prompt("first ask")` it is exactly
  `[user_message_chunk("first ask"), agent_thought_chunk("hmm"),
  agent_message_chunk("one"), agent_message_chunk("two"), tool_call
  call_0, tool_call_update call_0]` — compare the list to
  `[u["params"]["update"] for u in client.updates]` with the user chunk
  prepended, and assert no `user_message_chunk` was sent on the live
  turn (`client.chunks("user_message_chunk") == []`).
- `test_a_second_process_loads_the_session_and_replays_the_file`:
  process 1 as above; process 2 (a fresh `RawACPClient` with the same
  command) does `initialize()` then `load(session_id)`; assert
  `[u["params"]["update"] for u in client2.updates] == file before the
  load`, every replayed notification's `params.sessionId ==
  session_id`, the result has `configOptions` with the two default
  categories, and no `session/new` was needed. Then `prompt("second
  ask")` in process 2: the file now equals the old list +
  `[user_message_chunk("second ask"), …the first-turn script again]`
  (D122: the script ran again), and the live updates of process 2
  after the load are exactly those new entries minus the user chunk.
- `test_session_resume_answers_without_replaying`: `resume: True`;
  process 2 `initialize()` then `resume(session_id)`;
  `client2.updates == []` at the response; the result carries
  `configOptions`; a prompt afterwards appends to the same file.
- `test_loading_an_unknown_session_is_invalid_params`:
  `client.send("session/load", {"sessionId": "nope", "cwd": …,
  "mcpServers": []})` → `error.code == -32602`, `error.message == "no
  such session: nope"`.
- `test_resume_unadvertised_and_load_without_the_key_are_method_not_found`:
  `scenario(sessions={"dir": d})` (no `resume`) → `session/resume` is
  `-32601`; `scenario()` → `session/load` is `-32601` and
  `session/resume` is `-32601`. Fold the existing
  `test_an_unknown_method_is_a_json_rpc_error` into this or keep it
  and add the `resume` case beside it — either way both facts are
  asserted once.
- `test_mcp_servers_on_load_are_what_mcp_calls_connects_to` (uses the
  `mcp_server` fixture): process 1 `scenario(sessions=…,
  advertise_mcp=True, mcp_calls=[{"tool": "append_log", "args":
  {"text": "later"}}])`, `handshake()` with **no** servers, no prompt;
  process 2 `initialize()`, `load(session_id, mcpServers=[server])`,
  `prompt()` → the `tool_call_update` carries `logged: later` and
  `TOKEN in mcp_server["tokens"]`. Also assert, via `request_log`,
  that the recorded `session/load` params carry the server list.
- `test_a_misshapen_value_is_an_error_too` gains
  `pytest.raises(ScenarioError, match="sessions")` for
  `scenario(sessions={"dir": 1})` and `scenario(sessions={"dir": d,
  "replay": True})`.

Every test uses `tmp_path` for `dir`. No test sleeps; the file is
written synchronously before the fake answers the request that caused
the write, so reading it after `await client.prompt()` is
deterministic.

## Out of scope

- `athanore/agents/acp.py`, `session_id=` on `ACPAgent`, the replaying
  flag, the `notice`, the stats rules — all T089.
- `tests/agents/test_acp_lifecycle.py`, `tests/test_public_api.py` —
  T089.
- Keeping the subprocess alive; `session/fork`, `list`, `delete`,
  `close`; checking `cwd`; recording anything but updates.
- `session_file` (pi's layout) is untouched and is still written at
  startup with the process's own uuid; a scenario combining it with
  `sessions` is not exercised and not promised.
- `docs/site/`, `web/`, the OpenAPI snapshot, the generated client.
- `examples/`: no example uses `sessions` yet; the `chat` workflow's
  move to a held session is T089's or later.

## Verification

```sh
./scripts/dev.sh "uv run pytest -q tests/testing/test_fake_acp.py"
./scripts/dev.sh "uv run pytest -q tests/agents tests/testing"   # nothing downstream moved
./scripts/test.sh
git diff --exit-code tests/snapshots web/src/api/gen
```

`ruff` line length 88 and `pyright` standard apply to
`athanore/testing/`; the fake stays stdlib-only (no new imports beyond
`os`/`json` it already has). `lint-imports` is unaffected — nothing new
is imported from the package.

## Done

- `sessions: {dir, resume?}` is a validated scenario key; `initialize`
  advertises from it; `session/new` writes `<dir>/<sessionId>.json`
  and every update sent plus one `user_message_chunk` per prompt lands
  in it in order; `session/load` re-sends the list verbatim then
  answers `{configOptions}` and keeps recording under the same id;
  `session/resume` does the same without the replay and only when
  advertised; `-32602 no such session: <id>` and `-32601` as
  specified; `mcpServers` on either is what `mcp_calls` uses. 13
  §Fakes and the module docstring carry the vocabulary; D259 rowed;
  T088 marked Done; gate green; snapshot and generated client
  byte-identical.

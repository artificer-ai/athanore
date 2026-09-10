# permission smoke test 2 — watch one agent request cross the channel

**Task.** Not a `Txxx` row: operator-requested work arriving through the
`feature` workflow, after the v1 build order. Nothing in
`docs/v1/17-serial-task-plan.md` changes, no `**Status.** Done.` line is
added, and — this is the unusual part — **no source file changes at
all.** This file is the scope fence.

**Specs.** `docs/v1/06-requests.md` §The model (the producer table: an
ACP permission is `mode=options` / `kind=permission` / `source=agent`;
an ACP form elicitation is `mode=form` / `kind=elicitation`), §Service,
§Wake-ups, §Restart durability (the paragraph on agent-raised requests
carrying **no ordinal**), §Timeouts, §Surfaces; `docs/v1/05-agents.md`
§Policies (`permission_policy` and `elicitation_policy`, and the
`ask`-degrades-outside-a-task rule), §Tooling tiers (the athanore-MCP
exemption); `docs/v1/08-api.md` §Requests (operator) and §Events (SSE);
`docs/v1/10-frontend.md` §Panes items 3 and 4 (the docked request panel
and the requests pane) and §Attention; `docs/v1/12-security.md`
§Authentication (why a non-loopback bind needs the operator token);
D9, D115, D123 (5) and (6), D124 (12), D182.

**A correction to the brief.** It cites `docs/v1/05-requests.md` and
`docs/v1/03-api.md`. Those do not exist: requests are **06**, the API is
**08**, and 05 is agents, 03 the domain model. The sections above are
the real ones.

## What this task is

The request channel is already built (T030–T033a, T044b, T064) and
already covered by unit and component tests. What has never been
watched is one request travelling the whole way in a **live** server,
raised by a real ACP agent, drawn in the SPA, answered by a person, and
carried back into the agent's blocked turn. This run does exactly that
and nothing else.

So the deliverable is an **observation, written into the run's work
log** — not code, not a test, not a document. The implement stage runs
two ordinary tool calls, watches what the operator sees, and reports.

### It has already half-happened

Measured during this planner stage, against the running server:

```
GET /api/runs/01M25YNWFY7B2Q4QWXW3K58S7C/requests
  8  agent permission options  "permission: Read this run's requests from the API"
  9  agent permission options  "permission: Fetch this run's requests with the operator token"
```

Request 9 in full carried the three options the Claude adapter offered
verbatim (`allow-once`/`allow_once`, `allow-with-updates`/`allow_always`,
`reject`/`reject_once`), a bounded `tool_call` of
`{title, kind: "execute", raw_input}` with the `…` cap of D123 (5), and
came back `pending: false`, `answer: "allow-with-updates"`,
`answered_by: "user"` — the operator answered it in the panel while the
architect's turn was blocked on it, and the turn continued.

That is the permission half of this test, seen once. The implement
stage's job is to make it reproducible and to write it down, and to
find out whether the **elicitation** half happens at all: the store has
never held a row with `kind=elicitation` (requests 1–6 are retained
away, 7 is a node-raised `question`, 8 and 9 are the two above).

## The two open questions, settled

### 1. The simplest node body that raises a request is **no node body**

Nothing is added to `athanore/engine/` and no workflow gains a
`human_input()` call. Two reasons, and the second is the forcing one:

- The brief names `agent → operator` requests — permissions and
  elicitations — and those have exactly one producer: the ACP client's
  `request_permission` / `create_elicitation` callbacks
  (`athanore/agents/acp.py:309` and `:331`) resolving through
  `athanore/agents/policies.py` under an `ask` policy. A node body
  calling `human_input()` would exercise the *other* producer (`source:
  node`, `kind: question`) and prove nothing about the one asked for.
- The policies are already set to `ask` on the seat that runs this very
  workflow. `workflows/feature/agents.py:95` carries
  `permission_policy = "ask"` and `:96` `elicitation_policy = "ask"`,
  committed deliberately as TEMPORARY in `14c99ed` and `21bd2e2` —
  `elicitation_policy` has no settings override, so turning it on for a
  test meant committing it. The wiring under test is therefore live in
  the stage that reads this plan, and adding a node body would be
  adding a second, weaker path to test instead of the real one.

**The simplest agent behaviour that opens a permission request** is one
tool call the seat's own settings do not pre-approve. Two are enough,
and they are the two the operator named:

1. read `AGENTS.md`;
2. run `git rev-parse --abbrev-ref HEAD` in a shell.

One caveat the implementer must know: a tool call on the **athanore MCP
server** — `append_log`, `submit_result`, `get_task` — is answered
`allow_once` without opening a request
(`policies.names_athanore_server`, 05 §Tooling tiers). Those calls will
not raise anything, and that is correct behaviour, not a fault.

### 2. Both kinds, with different standing

- **Permission is the assertion.** At least one `agent` / `permission` /
  `options` request must be opened, drawn, answered by the operator, and
  seen to unblock the turn. If it does not happen, the smoke test
  failed and the work log says so.
- **Elicitation is an observation attempt whose negative result is also
  a result.** `elicitation_policy="ask"` is implemented
  (`policies.resolve_elicitation`), unit-tested, and the connection is
  opened with `use_unstable_protocol=True` precisely so
  `elicitation/create` is not answered `method_not_found` (D124 (12)).
  What is unknown is whether *this adapter* ever sends one. The
  implementer makes one honest attempt — if the seat has a question or
  choice tool (Claude Code's `AskUserQuestion`, or the plan-mode exit
  prompt), use it once with a small two-option question, which is the
  route an adapter takes to `elicitation/create` — and records what
  happened either way. It does **not** go hunting for a way to force
  one, and it does **not** add code to raise one: that is the brief's
  "no new elicitation scenarios".

## What the implement stage does, in order

1. Read `AGENTS.md`. Approve nothing yourself — wait for the operator.
2. Run `git rev-parse --abbrev-ref HEAD` in a shell and report the
   branch it printed.
3. Make the one elicitation attempt of §2 above, if the seat has a tool
   for it. If you are offered a choice or a form, take it.
4. Read this run's requests back and write the evidence into the work
   log with `append_log`, one line per request:

   ```
   id · source/kind/mode · the options offered · the option answered ·
   answered_by · seconds from created to answered · whether the turn
   continued afterwards
   ```

   The read is `GET /api/runs/{run_id}/requests` (08 §Requests). This
   server is not on a loopback bind, so it needs
   `Authorization: Bearer $(cat .athanore/token)` (12 §Authentication);
   the CLI's `athanore requests` is the same read with the token
   already found.
5. Say in the log whether an elicitation ever arrived, and if not, that
   it did not and what was tried.
6. **Change no file.** No edit, no create, no delete, no commit.

## The gate collision, stated rather than worked around

`gate` (`workflows/feature/__init__.py:338`) bounces back to `implement`
when `git rev-list plan_base..HEAD` is empty: "You made no commit on
`<branch>`. There is nothing to review." This task is defined by making
no commit, so the two cannot both be satisfied.

The boring choice, made here and recorded by this plan: **obey the
operator's instruction and let the gate bounce.** The operator wrote
"Expect the operator to cancel this run once the request channel has
been seen working" — cancellation is the intended end of this run, and
by the time the gate could run, the finding is already in the work log,
which is where it was wanted.

The implementer must **not** manufacture a commit to get past the
check. A file touched only so a gate counts something is exactly the
demo-grade path AGENTS.md forbids, and it would also break the brief's
"no persistent state or data changes". If the run is not cancelled and
the gate bounces the work back, the correct response is to append the
same finding again and say that there is nothing to commit — not to
invent something.

## Preconditions the operator owns

These are the two ways this test silently produces nothing. Check them
before starting the implement stage; neither is the implementer's to
change.

1. **The container Claude's permission mode.** With
   `~/.claude/settings.json` at `defaultMode: "bypassPermissions"` the
   adapter never sends `session/request_permission` at all, so no
   request is opened whatever `permission_policy` says. The operator's
   own commit messages name the `settings.json.bak` beside it. Requests
   8 and 9 above prove it is currently *not* bypassing.
2. **`settings.permission_policy` is unset.** It forces a global
   default over the agent's (`acp.py:200`); set to `auto_allow` for CI
   it would swallow every request. The reason the policy is hard-coded
   on the class rather than passed as `ATHANORE_PERMISSION_POLICY=ask`
   is in `14c99ed`'s message: the env var was lost across a restart and
   the run auto-approved its way through two stages without opening
   anything.

## What is being exercised, so the log can name it

Forward: `ACPClient.request_permission` (`athanore/agents/acp.py:309`)
→ `resolve_permission` `ask` arm (`athanore/agents/policies.py:326`) →
the requests port on `TaskContext` → `RequestService.create` (06
§Service) → the `requests` row and the `request.opened` event
(`athanore/events/names.py:62`) → SSE (`08` §Events) → the SPA.

Back: `POST /api/requests/{id}/answer` → `RequestService.answer` with
its ordered refusals (`invalid_option` 400, `already_answered` /
`stale_request` 409, 422) → `request.answered` → the `wait()` wake-up
with its missed-wake re-read (06 §Wake-ups) → `resolve_permission`
returns the `option_id` → `RequestPermissionResponse(outcome=selected)`
→ the agent's turn resumes.

## What the operator should see, and where

- **The docked request panel** under the agent stream while the focused
  task has an open request (10 §Panes item 3):
  `web/src/components/RequestPanel.tsx`, `data-testid="request-panel"`,
  one outlined button per option (`request-option`) styled by kind —
  `allow_*` accent, `reject_*` destructive. A `form` elicitation draws
  the RJSF form instead; if it ever appears, note that it *submits*,
  since a CSP that stopped it was a real defect once (D182).
- **The requests pane** in the run's pane cycle (10 §Panes item 4):
  `web/src/panes/kinds/Requests.tsx`, `pane-requests`, one
  `request-card` per request reading `agent → operator`, with the
  bounded `request-tool-call` block and, after answering,
  `request-answer` carrying `answered_by`.
- **The inbox** with no run selected (`web/src/components/Inbox.tsx`,
  `pane-inbox`, `inbox-count`), and the `⚠` on the run's NODE cell plus
  the tab-title count (10 §Attention).
- **The CLI**, as the second surface: `athanore requests`,
  `athanore permit <id> [option]`, `athanore deny <id>` (06 §CLI).

## Tests

**None are added.** The behaviour under test already has its tests at
the lowest layer that can express it (13 §Pyramid) —
`tests/agents/test_policies.py`, `tests/agents/test_acp_lifecycle.py`,
`tests/store/test_requests_repo.py`, `tests/api/test_requests_api.py`,
`web/src/components/__tests__/RequestPanel.test.tsx` — and what this
run adds is the one thing a test cannot supply: a real adapter, a real
browser and a real person. Writing a new test here would restate a
covered fact and, worse, imply the run had built something.

The gate is not run for this task. There is no diff to gate.

## Decisions

No row is added to `docs/v1/15-decisions.md`. Every choice above is a
choice about how to *run a test* — nothing about the product's
behaviour is decided, no code changes, and a decision row that records
"we did not write any code" would be noise in a log of design
commitments. This plan is the record. That is itself a judgement call
where the documents are silent, and it is stated here so a reviewer can
disagree with it in one place.

## Follow-up that belongs to the operator, not to this branch

`14c99ed` and `21bd2e2` must be reverted once this is seen working —
`permission_policy` back to `auto_allow`, `elicitation_policy` back to
`decline`, and the container's `defaultMode` back to
`bypassPermissions` from the `.bak`. An unattended build must never
block on a dialog nobody is watching. That is a change to `main` after
this run ends, and the implementer must not do it here: this branch is
expected to be cancelled and thrown away.

## Done

- The run's work log carries an entry from `implement` naming at least
  one request by id with `source: agent`, `kind: permission`,
  `mode: options`, the options as the adapter offered them, the option
  the operator picked, `answered_by: user`, the time it took, and the
  fact that the agent's turn continued afterwards.
- The elicitation attempt is recorded with its outcome — the request id
  if one arrived, or a plain statement that none did and what was tried.
- `git status --porcelain` is empty and `git rev-list plan_base..HEAD`
  is empty: nothing was built and nothing was left behind.
- No file under `athanore/`, `web/`, `tests/` or `docs/v1/` differs
  from `main`.

## Files

```
docs/plans/permission smoke test 2-observe-the-request-channel.md   (this file, the planner's commit)
```

And nothing else. Any other path in the branch diff means the fence
was crossed.

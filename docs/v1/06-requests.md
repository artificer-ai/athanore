# 06 — Requests: the human-in-the-loop channel

One first-class object for everything that blocks on a person. Carried
from `docs/design/requests.md` (implemented in the MVP) with the storage
cleaned up and the waiting semantics fixed (04 §Waiting).

## The model

```
Request  id, run_id, task_id, prompt, mode, source, kind,
         options? [{option_id, name, kind}], schema?, tool_call?, created
Answer   request_id (unique), author, option_id? | value?, consumed, created
```

- `mode` — the shape of the answer: `options` (pick one), `form` (object
  matching `schema`), `text` (non-empty string).
- `source` — `agent` or `node`; `kind` — `permission`, `elicitation`,
  `question`. Labels for the UI; nothing keys on them.
- One answer per request, claimed exactly once by the waiter that opened
  it. No FIFO, no untargeted answers.

| Producer | mode | kind | Answer goes to |
|---|---|---|---|
| ACP permission | options (agent's list verbatim) | permission | ACP `RequestPermissionResponse` |
| ACP elicitation (form) | form (agent's `requestedSchema`) | elicitation | ACP `accept` + content |
| `human_input(prompt)` | text | question | body, as `str` |
| `human_input(prompt, options=[…])` | options | question | body, as option id |
| `human_input(prompt, output_model=M)` | form (M's schema) | question | body, as validated `M` |
| HTTP ask | text / options / form | question | agent, via long-poll |

**Authority never blurs:** an answer is a value. A node's answer feeds
deterministic Python that routes; an agent's answer feeds a probabilistic
process mid-turn. Neither can move the graph.

## Service (`athanore.requests.service`)

```python
async def create(run_id, task_id, prompt, *, mode, source, kind, options=None, schema=None, tool_call=None, ordinal=None) -> Request
async def reopen(task_id, ordinal) -> Request | None # the node-raised request with that ordinal on this task row, answered or not
async def answer(request_id, *, option_id=None, value=None, author="user") -> Answer
async def wait(request_id, timeout=None) -> Answer   # claims (consumed=1); raises TimeoutError
async def poll(request_id, wait_s) -> Answer | None  # HTTP ask long-poll; idempotent re-delivery
def register_validator(request_id, fn); def unregister_validator(request_id)
def register_schema_validator(request_id, schema)   # the same, for a registrant holding a JSON schema (the ACP bridge, 05)
async def view(request_id) -> RequestView       # the read every method above makes first
async def list_for_run(run_id) -> list[RequestView]; async def inbox() -> list[RequestView]
```

`create` refuses an `options` request that offers nothing, with
`ValueError`: `answer()` accepts only an `option_id` the request listed,
so such a row is a question no answer could ever satisfy, and the honest
place to say so is the call that would write it (D115).

Validation happens where the answer lands (`answer()`), in this order:

- an id that names no request → `RequestNotFound` (404). It is `view()`'s
  refusal, and `answer`, `wait` and `poll` all inherit it from that one
  read rather than each deciding what a missing row means (D115).
- A second answer → `AlreadyAnswered` (409). The unique constraint on
  `answers.request_id` is the guard; the read is the sentence, and an
  answer that lands between the two collides and gets the same refusal.
- A request whose task is no longer `in_progress`/`waiting` →
  `StaleRequest` (409).
- `options`: `option_id` must be offered → else `InvalidOption` (400).
- `text`: non-empty string, whitespace alone is not one → else
  `InvalidAnswer` (422). Stored exactly as it was given: the answer is
  the operator's, not the service's.
- `form`: must be an object; if a validator is registered it runs and may
  normalise the value → else `InvalidAnswer` with pydantic-style errors
  (422). `human_input` registers `output_model.model_validate`; the ACP
  bridge and HTTP ask register the light JSON-schema validator — the
  bridge through `register_schema_validator`, because `athanore.agents`
  may not import `athanore.requests` to build one (02 §Layering, D123).

What a validator returns is what is stored, so an answer is normalised
once, at the door. `answers.value` is a JSON column and a pydantic
instance is not JSON, so a `pydantic_validator`'s return is stored as its
`model_dump(mode="json")` and `human_input` re-validates it on the way
out to hand the body the instance it promised (D115). That is one decode
path rather than two: it is the same one a replay after a restart already
takes (§Restart durability).

### Wake-ups

`wait()` and `poll()` subscribe to the EventBus for `request.answered`
with a matching id, then re-check the store (missed-wake guard). No
polling loops, no shared `asyncio.Event` in the store.

### Restart durability

- Server dies mid-wait → the task returns to `ready` (same row, same
  id) → the body re-executes → each `human_input` call takes the next
  `ctx.request_ordinal` and calls `reopen(task_id, ordinal)`. If a
  request with that ordinal exists it is reused: answered → the answer is
  returned at once (the `consumed` flag is informational here; a replay
  on the same task row is not a second waiter), pending → the body parks
  on it. Only when no request exists at that ordinal is a new one opened.
  So a body that asks three questions in sequence and dies after the
  second re-asks nothing: answers one and two replay, question three is
  asked once. The MVP only re-attached to the *open* request and re-asked
  every earlier one.
- A retry or rerun is a new task row, so its ordinals start at 1 and it
  asks afresh. That is intended: a failed attempt's answers may have been
  the reason it failed.
- No validator is registered between the crash and the re-attach; an
  answer given in that gap is re-validated on replay, and if it no longer
  fits, the failure is logged and the question is re-asked with the
  errors appended (a new request at the next ordinal).
- Agent-raised requests die with their agent session (the whole attempt
  re-runs); they remain in history as stale. They carry **no ordinal**:
  an ordinal is a promise that the *n*th question of a re-executed
  attempt is the same question, and a turn is not reproduced statement
  for statement, so numbering a permission by position would replay one
  answer onto a different tool call.

### Timeouts and headless fallbacks

Unchanged from the MVP (05 §Policies): `permission_timeout` +
`permission_timeout_action` record an `engine`-authored answer;
elicitations past the timeout are declined; `human_input(timeout=…)`
raises `TimeoutError` into the body, which decides.

## Surfaces

### HTTP (08 has the full table)

```
GET  /api/requests?pending=true               inbox across runs (attention surface)
GET  /api/runs/{id}/requests                  every request of a run with answer state
POST /api/requests/{id}/answer                {"option_id"} | {"value"} → RequestView
POST /api/agent/tasks/{id}/ask                agent (task token, ask_policy=http)
GET  /api/agent/tasks/{id}/requests/{rid}?wait=N   agent long-poll (max 120 s)
```

### SPA (10)

- **Requests pane** in the selected run's pane cycle (the design mock's
  `messages` pane): one card per request, `node → operator` or
  `agent → operator`, pending first, answerable in place.
- **Docked request panel** under the agent stream while the focused task
  has open requests: `options` → one outlined button per option styled
  by kind (`allow_*` accent, `reject_*` destructive); `text` → input and
  send; `form` → generated form from the schema (the same renderer as
  plugin actions).
- With no run selected, the detail side shows the global requests pane:
  every open request across runs, newest first. The header shows the
  open count; a run with open requests carries `⚠` in its NODE cell.
- A new request on the selected run switches the pane to **agent** once;
  opt-out in settings.

### CLI (11)

`athanore requests [run]`, `athanore answer <req> <option|text|json>`,
`athanore permit <req> [option]`, `athanore deny <req>`. Request ids are
globally unique, so the run id is no longer required.

## Decisions

1. One request/answer object, three producers, keyed answers only
   (carried).
2. Validation at the landing point with waiter-registered validators
   (carried).
3. Waiting nodes release their pool slot (new; was explicitly deferred).
4. Requests and answers get their own tables; the MVP's polymorphic
   `messages` table is migrated (07).
6. Node requests carry an `ordinal` per task row so a recovered body
   replays earlier answers instead of re-asking (new).
5. Elicitation form mode bridged, URL mode declined, completion ignored
   (carried; revisit when ACP stabilises elicitation).

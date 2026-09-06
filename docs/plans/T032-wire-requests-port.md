# T032 — Wire `TaskServices.requests` and the ordinal counter

**Task.** `docs/v1/17-serial-task-plan.md` § `### T032`.
**Specs.** `docs/v1/06-requests.md` §Ordinals and re-execution;
`docs/v1/04-engine.md` §Waiting (why a re-executed body must re-attach).

## What this task is

The implementation behind T023's `RequestsPort` Protocol, and the
ordinal counter that makes a re-executed node body re-attach to the
request it already opened instead of asking twice.

## What this task is not

- No `human_input` (T033) — this is the layer under it.
- No new service logic; delegate to T031.
- Not unit-tested on its own: the task says it is covered through T033,
  which is correct, but do not take that as licence to leave it
  unexercised — T033's tests must actually drive this path.

## Steps

1. `reopen_or_create(prompt, *, mode, kind, options, schema)`:
   `ordinal = ctx.request_ordinal + 1` (incrementing on the context),
   then `existing = repo.by_ordinal(task_id, ordinal)` — return it if
   present, else `create(..., source="node", ordinal=ordinal)`.
   This is what makes a crash-and-recover mid-wait resume the same
   question: the body re-runs, asks for ordinal 3 again, and gets the
   request that is already open with the answer possibly already in it.
2. `create_agent_request(...)` — source `agent`, **no ordinal** (an
   agent's permission prompts are not replayable in position).
3. `answer_as_engine(request_id, option_id)`.
4. `wait`, `poll` delegating to the service.

## Verification

Covered by T033's suite, but make sure it covers *this*: a body that
opens two requests, is re-executed from the start, and re-attaches to
both by ordinal rather than opening four. Write that test here even
though the task lists none — otherwise the ordinal counter is untested
code in the middle of the recovery path.

## Done

- The port is implemented and exercised by T033's tests, including
  re-attachment.
- `**Status.** Done.` on `### T032`, in the same commit.

## Files

```
athanore/engine/services.py
docs/v1/17-serial-task-plan.md
```

# T045 — Agent router under `/api/agent/`

**Task.** `docs/v1/17-serial-task-plan.md` § `### T045`.
**Specs.** `docs/v1/08-api.md` §Agent endpoints;
`docs/v1/15-decisions.md` D39, D56 (the log excludes `stats` lines);
`docs/v1/12-security.md` §Task tokens.
**Reference.** v0's `tests/test_submissions.py`, `test_ask.py`.

## What this task is

The surface an agent talks to, authenticated by its task token and
nothing else. This is also where `MockAgent(submit=)` stops taking the
T037 shortcut and starts posting for real — delete that flag here.

## What this task is not

- No operator auth on these routes. `Depends(task_auth)` only, and the
  token scopes to exactly one task.
- No new submission semantics — T023's service and T035's helpers own
  them.

## Steps

1. `GET /tasks/{id}`: title and description from the run,
   `input = payload`, and the work log **without `kind=stats` lines**
   (D56) — an agent reading its own token counts back is noise.
2. `POST /log`.
3. `POST /submit`: read `ctx = engine.live.context_for(id)`; **409 if
   there is none** (the task is not running, so nothing can accept a
   submission); validate against `ctx.output_model`, then either
   `services.submissions.accept` or `reject` with 422
   `{errors, schema}`, setting `ctx.last_rejection` so the repair prompt
   can quote it.
4. `POST /ask`: **403 unless `ctx.ask_policy == "http"`** — an agent
   cannot grant itself the right to interrupt a human. `prompt`, plus
   optional `options` or `schema`, decide the mode.
5. `GET /requests/{rid}`: long-poll, `wait` clamped to 120 s, then
   `poll`.
6. Switch `MockAgent(submit=)` to the real endpoint and remove the T037
   flag.

## Verification

`tests/api/test_agent_api.py`, porting v0's two files:

- a misfit submission → 422 carrying the schema;
- the **last valid** submission wins;
- 409 after the task finishes;
- `/ask` → 403 when the policy is off;
- the long-poll returns as soon as an answer lands, not on the clamp.

## Done

- Tests pass; `MockAgent` no longer bypasses the API.
- Ledger rows for `test_submissions.py` and `test_ask.py` ticked.
- Snapshot and client regenerated.
- `**Status.** Done.` on `### T045`, in the same commit.

## Files

```
athanore/api/routers/agent.py
athanore/testing/mock.py
tests/api/test_agent_api.py
tests/snapshots/openapi.json
web/src/api/gen/**
docs/porting-ledger.md
docs/v1/17-serial-task-plan.md
```

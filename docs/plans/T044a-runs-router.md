# T044a — Runs router including `/graph` and `/position`

**Task.** `docs/v1/17-serial-task-plan.md` § `### T044a`.
**Specs.** `docs/v1/08-api.md` §Runs and §Graph semantics (the `state`
precedence table — implement it exactly); `docs/v1/15-decisions.md` D57
(position), D58 (output shape).
**Reference.** v0's `test_edit_run.py` and the API halves of
`test_management.py`, `test_pause.py`, `test_run_log.py`,
`test_priority.py`.

## What this task is

The biggest router: every operator verb on a run, plus the graph view
the SPA draws from.

## What this task is not

- No new engine behaviour. Every verb delegates to `Ops` (T027a/T027b);
  if a precondition feels missing, it belongs there.
- No SSE (T045).

## Steps

1. `routers/runs.py`: every row of 08 §Runs.
2. `/graph` per 08 §Graph semantics — `state` precedence, `live`,
   `attempts`, `last_task_id`, `branches` from the `branch` frames,
   `join` and `arrivals` from `JoinRepo.incomplete`, and `edges[].kind`
   (`forward` / `back` / `join`) with `traversed`. The precedence table
   is the part to transcribe rather than reinvent: two states can be
   true at once and the order decides what the operator sees.
3. `/position` per D57.
4. `RunDetail.outputs` from `terminal_tasks`.

## Verification

`tests/api/test_runs_api.py`, porting the four API halves:

- graph `state` precedence on a run with a retry pending;
- a fan-out run reports its branches;
- a join reports `2 of 3`;
- `position {index}` clamps at both ends;
- **no `token` or `token_hash` key anywhere in any response** — a
  recursive walk over every response body in the suite, not a spot
  check. This is the test that makes the header-only rule structural.

## Done

- Tests pass; the recursive token walk is in place.
- Ledger rows ticked for `test_edit_run.py` and the four API halves.
- Snapshot and client regenerated.
- `**Status.** Done.` on `### T044a`, in the same commit.

## Files

```
athanore/api/routers/runs.py
tests/api/test_runs_api.py
tests/snapshots/openapi.json
web/src/api/gen/**
docs/porting-ledger.md
docs/v1/17-serial-task-plan.md
```

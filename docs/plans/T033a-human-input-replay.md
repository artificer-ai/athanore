# T033a — `human_input`: ordinal replay after a crash

**Task.** `docs/v1/17-serial-task-plan.md` § `### T033a`.
**Specs.** `docs/v1/06-requests.md` §Re-execution;
`docs/v1/15-decisions.md` D44.

## What this task is

The behaviour that makes durability survive a human in the loop: a body
that already asked three questions and got two answers must re-run
without asking those two again.

## What this task is not

- No new storage. T032's ordinals already record the position.
- Not a cache. A **retry** (a new task row) starts its ordinals at 1 and
  asks afresh — replay is per attempt of the same task, and conflating
  the two would silently reuse a stale operator answer.

## Steps

1. In `human_input`, when `reopen_or_create` returns a request that
   **already has an answer**: validate it (via `pydantic_validator` for
   a form), and on success return it without waiting.
2. On a stale-fit failure — the answer no longer validates because the
   `output_model` changed — log the errors, append them to the prompt,
   and open a **new** request at the next ordinal. Do not silently drop
   the mismatch and do not fail the body.
3. A pending existing request is **waited on**, never re-created.

## Verification

`tests/requests/test_human_input_replay.py`:

- three questions; kill the attempt after two answers (cancel the
  asyncio task, reset the row to `ready` the way recovery does, re-run):
  the third attempt asks only question three, and questions one and two
  return their replayed answers;
- a replayed form answer that no longer validates re-asks at **ordinal
  4** with the errors attached;
- a retry (a new task row) starts its ordinals at 1 and asks afresh.

## Done

- Tests pass; the retry case is asserted, not assumed.
- `**Status.** Done.` on `### T033a`, in the same commit.

## Files

```
athanore/requests/human.py
tests/requests/test_human_input_replay.py
docs/v1/17-serial-task-plan.md
```

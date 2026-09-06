# T016 — Repositories part 3: requests and answers

**Task.** `docs/v1/17-serial-task-plan.md` § `### T016`.
**Specs.** `docs/v1/06-requests.md` (the model: pending, stale,
consumed); `docs/v1/08-api.md` §Requests (the fields `RequestView`
exposes); `docs/v1/07-storage.md` §Schema.

## What this task is

The last repository: the human-in-the-loop channel's persistence, and
the joined view the inbox is built on.

## What this task is not

- **T033 onward** write the request *service* — create/answer/wait,
  validators, policies. This task stores and reads; it decides nothing.
- No HTTP. `RequestView` is a read model, not an API schema.
- Do not swallow the double-answer `IntegrityError`. Raise it; the
  service maps it to an error code later.

## Steps

1. `repos/requests.py`: `create(...)` with the full signature the task
   lists, `get`, `by_ordinal(task_id, ordinal)`, `answer(request_id,
   author, option_id=None, value=None) -> AnswerRow`,
   `mark_consumed(request_id)`.
2. `view(id)` and `list_views(run_id=None, pending_only=False)` as **one**
   query joining `requests ⟕ answers ⟗ tasks`, computing:
   - `pending = answer IS NULL AND task.status IN ('in_progress','waiting')`
   - `stale   = answer IS NULL AND NOT pending`
   - `node = task.node`, `age = now - created`.
   The pending/stale distinction is the whole point: an unanswered
   request whose task died is not waiting for anyone, and must not sit
   in the operator's inbox forever.
3. `RequestView` in `rows.py`, fields per 08 §Requests.

## Verification

`tests/store/test_requests_repo.py`:

- a second answer to the same request raises;
- the view flags pending vs stale purely by task status — build one of
  each and assert both;
- `list_views(pending_only=True)` excludes answered **and** stale;
- `by_ordinal` finds the request and returns `None` for a gap.

## Done

- Tests pass on both backends; pyright strict clean.
- `**Status.** Done.` on `### T016`, in the same commit.

## Files

```
athanore/store/repos/requests.py
athanore/store/rows.py            (RequestView)
tests/store/test_requests_repo.py
docs/v1/17-serial-task-plan.md
```

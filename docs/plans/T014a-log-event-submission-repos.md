# T014a — `LogRepo`, `EventRepo`, `SubmissionRepo`

**Task.** `docs/v1/17-serial-task-plan.md` § `### T014a`.
**Specs.** `docs/v1/07-storage.md` §Schema and §Retention;
`docs/v1/03-domain-model.md` §Work log (what an author and a kind mean).

## What this task is

Three small repositories in T014's pattern: the work log, the event
table, and agent submissions.

## What this task is not

- **T017** writes the retention *job*. `prune` here is the query it will
  call, nothing scheduled.
- **T044** writes the SSE endpoint. `list_after` is the cursor query it
  will use; no HTTP here.
- No stream chunks — T014b.

## Steps

1. `repos/log.py`: `append(run_id, node, author, text, task_id=None,
   kind=None) -> LogEntryRow`; `list(run_id, after=0, limit=None,
   exclude_kinds=())`. `exclude_kinds` is what lets a reader see the
   deliverables without the `stats` noise.
2. `repos/events.py`: `insert_many(events) -> list[int]` (the outbox's
   write path from T013a — one statement, ids returned in order);
   `list_after(after, limit, run_id=None, patterns=None)` using T009's
   `matches` semantics for the glob; `list_for_run`; `prune(before,
   keep_prefix="run.")`.
3. `repos/submissions.py`: `insert(task_id, payload)`, `latest(task_id)`,
   `list(task_id)`.

## Verification

- `exclude_kinds=("stats",)` drops stats lines and keeps everything else;
- `list_after` honours cursor, limit, run filter **and** glob patterns —
  test a `run.*` pattern against a `run.a.b` name, so the one-segment
  rule is enforced at the query layer too;
- `prune(before)` keeps `run.*` and removes the rest;
- `latest(task_id)` returns the highest id, not the first inserted.

## Done

- The three test modules pass; pyright strict clean.
- `**Status.** Done.` on `### T014a`, in the same commit.

## Files

```
athanore/store/repos/{log.py,events.py,submissions.py}
tests/store/{test_log_repo.py,test_events_repo.py,test_submissions_repo.py}
docs/v1/17-serial-task-plan.md
```

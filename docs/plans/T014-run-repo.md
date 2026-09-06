# T014 — `RunRepo`

**Task.** `docs/v1/17-serial-task-plan.md` § `### T014`.
**Specs.** `docs/v1/07-storage.md` §Schema and §Queries;
`docs/v1/03-domain-model.md` §Run (statuses, ordering, what a summary
shows).

## What this task is

The first repository, and the pattern every later one copies: Core
queries returning frozen rows from T010, attached to `UnitOfWork` for
writes and to a read-only `Reader` facade for reads.

## What this task is not

- No task, log, request or stream queries — T014a, T015 and T016.
- No engine and no API. Ordering here is `position`; what *uses* it is
  the scheduler's business later.
- No ORM relationships. Aggregates come from explicit subqueries.

## Steps

1. `repos/base.py`: `Repo(conn)` with `_row(model, Row)`.
2. `repos/runs.py`:
   - `insert(workflow, title, description) -> RunRow` — ULID id,
     `status=queued`, `position = COALESCE(MAX(position), 0) + 1`;
   - `get(id)`;
   - `list(status=None, workflow=None) -> list[RunSummary]` — **one**
     query with two correlated scalar subqueries: `current_nodes` as
     `GROUP_CONCAT`/`string_agg` of distinct nodes whose task status is
     `in_progress` or `waiting`, and `pending_requests` as the count of
     unanswered requests on those tasks. Not N+1, not a Python loop over
     runs;
   - `detail(id) -> (RunRow, list[TaskRow], RunStats)` — stats summed
     with `SUM(json_extract(stats, '$.input_tokens'))` and friends,
     dialect-switched between SQLite and Postgres;
   - `update(id, **fields)` touching `updated`;
   - `set_status(id, status, finished=None)`;
   - `swap_position(id, direction)`, `move_position(id, index)` (one
     `UPDATE … CASE`, not a loop), `compact_positions()`;
   - `delete(id)` — a single `DELETE` that relies on the cascades T011
     declared.
3. Wire the repo onto `UnitOfWork` and onto the read-only `Reader`.

## Careful

`RunStats` must stay honest: a run whose tasks recorded no stats gets
`None` fields, not zeros (`AGENTS.md` — real data only, unknown is
omitted). `SUM` over no rows returns `NULL`; do not `COALESCE` it to 0.

## Verification

`tests/store/test_runs_repo.py`:

- positions append at `max+1`;
- `swap_position` with no neighbour is a no-op returning the same
  position;
- `move_position(id, 0)` renumbers 1..n with no gaps or duplicates;
- `list()` aggregates correctly for a run with two in-flight nodes and
  one open request;
- `detail()` sums stats across attempts **including failed ones**;
- `delete` cascades to tasks, logs and events.

## Done

- Tests pass; pyright strict clean on `athanore/store`.
- `list()` issues one query — assert it, or read the echoed SQL once and
  say so in the report.
- `**Status.** Done.` on `### T014`, in the same commit.

## Files

```
athanore/store/repos/base.py
athanore/store/repos/runs.py
athanore/store/uow.py            (wiring)
tests/store/test_runs_repo.py
docs/v1/17-serial-task-plan.md
```

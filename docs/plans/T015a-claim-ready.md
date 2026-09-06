# T015a — `TaskRepo.claim_ready`

**Task.** `docs/v1/17-serial-task-plan.md` § `### T015a`.
**Specs.** `docs/v1/04-engine.md` §Dispatch order (the SELECT, verbatim);
`docs/v1/15-decisions.md` D38 and D41 (why the order is what it is);
`docs/v1/12-security.md` §Task tokens.
**Reference.** v0's `tests/test_priority.py` in the sibling checkout —
its ordering assertions are what this task's tests port
(`docs/porting-ledger.md` row, ticked here).

## What this task is

The one query in the store with real concurrency semantics: pick the
next tasks, claim them so nobody else can, and mint a token per claimed
attempt. Everything about the engine's fairness lives in its ORDER BY.

## What this task is not

- No dispatch loop, no pools, no worker accounting — T032 onward.
- Do not re-derive the ordering. 04 §Dispatch order specifies it; D38
  and D41 say why. If your SELECT differs from the document, the SELECT
  is wrong.

## Steps

1. The SELECT of 04 §Dispatch order, with `FOR UPDATE SKIP LOCKED` when
   the dialect is postgresql.
2. For each id: `token = secrets.token_urlsafe(32)`,
   `token_hash = sha256(token).hexdigest()`.
3. `UPDATE tasks SET status='in_progress', started=now, token_hash=?
   WHERE id=? AND status='ready'` — the `AND status='ready'` is the
   claim. A rowcount of 0 means somebody else won; skip that id rather
   than raising.
4. For each distinct run still `queued`, flip to `running` and report
   `run_started=True` **once**, so `run.started` is emitted once.
5. Re-select the claimed rows in claimed order and return
   `ClaimedTask = (TaskRow, token, run_started)` — the clear-text token
   is returned to the caller and never stored.

## Verification

`tests/store/test_claim.py`, porting v0's ordering assertions:

- run position dominates;
- explicit priority beats generation;
- `-generation` orders downstream first;
- equal keys → newer `created` first;
- a retry carrying the old `created` does not jump the queue;
- `limit` is respected;
- tokens are unique per claim, the stored hash matches, and the clear
  text appears nowhere in the row (`assert token not in str(row)`);
- a second `claim_ready` returns nothing;
- `queued → running` is flagged exactly once;
- **paused runs are never claimed** — the test that keeps operator pause
  meaningful.

Run it under both backends (T014b's fixture); the Postgres leg is the
only one that exercises `SKIP LOCKED`.

## Done

- Tests pass on SQLite and Postgres.
- `docs/porting-ledger.md` row for `tests/test_priority.py` ticked (its
  API half is ported in T044a — note that in the row rather than
  claiming the file is fully covered).
- `**Status.** Done.` on `### T015a`, in the same commit.

## Files

```
athanore/store/repos/tasks.py
tests/store/test_claim.py
docs/porting-ledger.md
docs/v1/17-serial-task-plan.md
```

# T027a — Operator ops, part 1: submit, edit, reorder, pause, resume, append_log

**Task.** `docs/v1/17-serial-task-plan.md` § `### T027a`.
**Specs.** `docs/v1/04-engine.md` §Operator operations (the preconditions
table); `docs/v1/15-decisions.md` D57 (reorder semantics).
**Reference.** v0's `tests/test_edit_run.py`, `test_run_log.py`,
`test_pause.py` — engine-level assertions ported here, ledger rows
ticked.

## What this task is

The operator verbs that do not destroy anything. Each is one uow plus
its events plus `notify()` where dispatch could change.

## What this task is not

- **T027b** owns cancel, delete, rerun, retry, move, set_status.
- No HTTP. Preconditions raise the T027 exceptions; T030 maps them.
- No new statuses or events — 04 and 18 already name them.

## Steps

Each op: one uow, events, `notify()` when relevant, preconditions from
04 mapped onto `Conflict` / `NotFound` / `UnknownWorkflow`.

- `submit(wf, title, description)` — run `queued`, one start task with
  payload `{title, description}`, lineage `start`.
- `edit(run, title?, description?)` — an empty title is a `Conflict`;
  emit `run.updated {changed}` naming only what changed.
- `reorder(run, direction | index)` per D57.
- `pause(run)` / `resume(run)` — pause stops the **next** claim; an
  in-flight body finishes. Killing running work is `cancel`, which is
  T027b's, and conflating the two is the mistake this split exists to
  prevent.
- `append_log(run, text)` — author `user`, node = the single in-flight
  node, or `"user"` when there is not exactly one.

## Verification

`tests/engine/test_ops_basic.py`, porting the v0 engine-level
assertions:

- pause blocks the next claim while the in-flight body runs to
  completion;
- resume dispatches again;
- `edit` rejects an empty title with `Conflict`;
- reorder swaps with a neighbour and clamps at the ends;
- `append_log` picks the in-flight node when there is exactly one and
  `"user"` otherwise.

## Done

- Tests pass; ledger rows for the three v0 files noted as engine-half
  ported (their API halves land in T044a).
- `**Status.** Done.` on `### T027a`, in the same commit.

## Files

```
athanore/engine/ops.py
tests/engine/test_ops_basic.py
docs/porting-ledger.md
docs/v1/17-serial-task-plan.md
```

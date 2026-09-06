# T066d — Edit run and pickers

**Task.** `docs/v1/17-serial-task-plan.md` § `### T066d`.
**Specs.** `docs/v1/10-frontend.md` §Overlays and §Keyboard;
`docs/v1/04-engine.md` §Operator operations (what each picker posts).

## What this task is

Four palette-style pickers — retry, move, cancel, rerun — plus editing a
run's title and description.

## What this task is not

- No new operator semantics. Each picker is a list plus one POST.
- **Move must not offer a join node**: T024c makes that a `Conflict`,
  and offering it would be an error you can only discover by trying.

## Steps

1. Edit run: title and description → `PATCH`.
2. Pickers, each a palette-style list of the selected run's tasks
   (node, attempt, status):
   - `t` retry,
   - `m` move — the task list, then the node list, **filtered to exclude
     joins**,
   - `x` cancel task,
   - `r` rerun — the node list.
3. Each posts the endpoint T044a exposed.

## Verification

Vitest:

- each picker posts the right endpoint and body;
- move hides join nodes in the target list;
- a picker on a run with no eligible tasks says so rather than showing
  an empty box.

## Done

- Tests pass.
- `**Status.** Done.` on `### T066d`, in the same commit.

## Files

```
web/src/overlays/{EditRun,Pickers}.tsx
web/src/**/__tests__/**
docs/v1/17-serial-task-plan.md
```

# T066e — Task drawer and keys overlay

**Task.** `docs/v1/17-serial-task-plan.md` § `### T066e`.
**Specs.** `docs/v1/10-frontend.md` §Task drawer and §Keyboard;
`docs/v1/04-engine.md` §Operator operations (the completeness check).

## What this task is

Everything about one task in one place, and the overlay that lists the
keys. This is the task whose Done condition is a **completeness** claim:
every operator op of 04 reachable from the UI.

## What this task is not

- No new endpoints.
- No drawer-local state that outlives the overlay: `?overlay=task&task=`
  is the state.

## Steps

1. The task drawer: payload, result, error, submissions, stats, lineage,
   branch; retry / move / set-status actions; and a "focus stream"
   button feeding T063c.
2. The keys overlay: the footer chips, expanded.
3. Every overlay closes on `esc` and is driven by `?overlay=`.

## Verification

Vitest:

- the drawer renders a failed attempt with its lineage;
- the actions post;
- the keys overlay lists **every** binding in 10 §Keyboard — iterate the
  spec's table rather than hand-listing, so a new binding cannot be
  forgotten here.

Then walk 04 §Operator operations and confirm each one is reachable from
the UI. List them in the report; that is the Done condition.

## Done

- Tests pass; every operator op reachable, enumerated in the report.
- `**Status.** Done.` on `### T066e`, in the same commit.

## Files

```
web/src/overlays/{TaskDrawer,Keys}.tsx
web/src/**/__tests__/**
docs/v1/17-serial-task-plan.md
```

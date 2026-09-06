# T066b — New run overlay

**Task.** `docs/v1/17-serial-task-plan.md` § `### T066b`.
**Specs.** `docs/v1/10-frontend.md` §Overlays;
`docs/v1/15-decisions.md` D34, D57.

## What this task is

Submitting a run from the UI, including the position choice that decides
whether it goes to the front of the queue or the back.

## What this task is not

- No client-side validation beyond what zod expresses; the server is
  still the authority.
- No new endpoint for "submit at top": it is `POST …/runs` followed by
  `POST …/position {index: 0}` (D57), and both must succeed.

## Steps

1. A WORKFLOW chip group, TITLE, DESCRIPTION, and POSITION top/bottom.
   Top → submit, then position to index 0.
2. A read-only ENTRY NODE read from the selected workflow's graph, so an
   operator can see where the run will start.
3. `⌘⏎` submits; cancel closes. react-hook-form + zod.

## Verification

Vitest:

- the right bodies posted for top and for bottom — including that the
  position call is **not** made for bottom;
- an empty title is blocked;
- the entry node updates when the workflow chip changes.

## Done

- Tests pass.
- `**Status.** Done.` on `### T066b`, in the same commit.

## Files

```
web/src/overlays/NewRun.tsx
web/src/**/__tests__/**
docs/v1/17-serial-task-plan.md
```

# T063d — Requests pane renderer

**Task.** `docs/v1/17-serial-task-plan.md` § `### T063d`.
**Specs.** `docs/v1/10-frontend.md` §Requests;
`docs/v1/06-requests.md` §Kinds.

## What this task is

The cards an operator reads before answering: who asked, when, what, and
either the answer already given or the space where the controls will go.

## What this task is not

- **No controls.** T064 adds them; this task renders the slot. That is
  the split the plan chose, so resist wiring a button.
- No answering logic, no optimistic updates.

## Steps

1. Cards labelled `node → operator` or `agent → operator`, **pending
   first**, with timestamp and prompt.
2. Then either the answer (with its author — `engine` when a timeout
   answered it, which is exactly when an operator wants to know) or the
   controls slot.
3. Permission cards render the bounded tool-call summary T038 stores.

## Verification

Vitest:

- ordering, pending before answered;
- an answered card shows author and value;
- the tool-call summary renders, and a long one stays bounded.

## Done

- Tests pass.
- `**Status.** Done.` on `### T063d`, in the same commit.

## Files

```
web/src/panes/kinds/Requests.tsx
web/src/**/__tests__/**
docs/v1/17-serial-task-plan.md
```

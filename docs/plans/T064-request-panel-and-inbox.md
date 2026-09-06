# T064 — Docked request panel, `ActionForm`, inbox

**Task.** `docs/v1/17-serial-task-plan.md` § `### T064`.
**Specs.** `docs/v1/10-frontend.md` §Requests and §Forms;
`docs/v1/06-requests.md` §Modes; `docs/v1/15-decisions.md` D49.

## What this task is

Answering, from the UI. The mode decides the control, the 422 shape
decides where an error appears, and the panel appears wherever the
operator already is.

## What this task is not

- No new endpoints. One POST to `/api/requests/{id}/answer`.
- No optimistic answering: a 409 (someone else answered, or the request
  went stale) is a toast, not a silent overwrite.
- No custom form runtime — RJSF with the Nocturne theme.

## Steps

1. `ActionForm`: `@rjsf/core` + `@rjsf/shadcn` themed with Nocturne
   tokens, `validator-ajv8`, and **`extraErrors` populated from a 422's
   `errors[]`, mapping `loc` → RJSF path**. That mapping is the point of
   T030's careful `loc` paths: a server-side rejection lands on the
   field that caused it.
2. `RequestPanel` by mode: `options` → outlined buttons styled by kind
   (`allow_*` accent, `reject_*` destructive, others neutral); `text` →
   input plus send; `form` → `ActionForm(schema)`.
3. Placement: docked under the agent stream when the focused task has
   open requests; the same component inside the requests-pane cards and
   the global inbox (newest first, count in the header).
4. Tab title prefix `(n)`; desktop notifications **opt-in**.

## Verification

Vitest:

- a nested schema round-trips through the form;
- a 422 maps onto the right field;
- option kind classes per kind.

Then the task's Done: allow a permission raised by `FakeACPAgent` from
the UI, end to end.

## Done

- Tests pass; a real permission answered from the browser.
- `**Status.** Done.` on `### T064`, in the same commit.

## Files

```
web/src/components/{ActionForm,RequestPanel,Inbox}.tsx
web/src/**/__tests__/**
docs/v1/17-serial-task-plan.md
```

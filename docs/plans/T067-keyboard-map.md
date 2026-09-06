# T067 — Keyboard map and focus scoping

**Task.** `docs/v1/17-serial-task-plan.md` § `### T067`.
**Specs.** `docs/v1/10-frontend.md` §Keyboard (the exact table);
`docs/v1/15-decisions.md` D51.

## What this task is

One keymap hook, and the scoping rules that stop it firing when the user
is typing or an overlay owns the keyboard.

## What this task is not

- No new bindings. 10's table is the contract.
- No global listener that ignores context: a `d` typed into the filter
  input must **not** delete anything, which is the entire reason
  scoping exists.

## Steps

1. `useKeymap()` implementing 10 §Keyboard exactly.
2. Suppressed when `event.target` is an input, textarea or
   contenteditable, or when an overlay owns focus — overlays register
   their own scope.
3. `a` / `d` only when the request panel has focus.
4. `D` (shift) opens the delete confirmation; `^r` invalidates all
   queries; `?` opens the keys overlay.

## Verification

Vitest:

- `d` while the list has focus does nothing;
- `D` opens the confirm;
- `a` answers **only** with the request panel focused;
- a key typed into the filter input never triggers an action.

## Done

- Tests pass, scoping included.
- `**Status.** Done.` on `### T067`, in the same commit.

## Files

```
web/src/keys/useKeymap.ts
web/src/**/__tests__/**
docs/v1/17-serial-task-plan.md
```

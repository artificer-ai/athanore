# T066a — Command palette

**Task.** `docs/v1/17-serial-task-plan.md` § `### T066a`.
**Specs.** `docs/v1/10-frontend.md` §Palette and §Keys.

## What this task is

cmdk in a dialog: every operator action and every overlay, each with its
keyboard shortcut shown, so the palette doubles as the shortcut list.

## What this task is not

- No new actions. It lists what exists; if something is missing from the
  palette it is missing from the app.
- Plugin actions appear here from T070; leave the section wired but
  empty.

## Steps

1. cmdk inside a `Dialog`, with a `›` input and rows of
   `name · hint · key`.
2. Every operator action and every overlay, listed with its key.
3. Plugin actions appended under `plugin: <title>`.

## Verification

Vitest:

- filtering narrows the list;
- enter runs the highlighted action;
- `esc` closes and returns focus where it was — focus restoration is the
  part that gets skipped and is the part keyboard users notice.

## Done

- Tests pass.
- `**Status.** Done.` on `### T066a`, in the same commit.

## Files

```
web/src/overlays/Palette.tsx
web/src/**/__tests__/**
docs/v1/17-serial-task-plan.md
```

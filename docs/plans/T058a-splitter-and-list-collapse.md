# T058a — Splitter and list collapse

**Task.** `docs/v1/17-serial-task-plan.md` § `### T058a`.
**Specs.** `docs/v1/10-frontend.md` §Chrome; `docs/v1/15-decisions.md`
D71 (the CRT chrome was removed from the mock; D36 is superseded).

## What this task is

Two pieces of chrome: a resizable splitter and a collapsible run list.

## What this task is not

- **No CRT chrome.** The mock no longer has scanlines, a scan band, a
  vignette or a flicker, and there is no `crt` preference and no
  settings toggle (D71). If you have seen an older mock or an older
  draft of this plan, `docs/v1/design/Athanore.dc.html` is the
  reference.
- No content changes. This is chrome only.

## Steps

1. `Splitter` via `react-resizable-panels`: min 260, max
   `window − 340`, a 5 px handle, width persisted to prefs.
2. List collapse to the 30 px `RUNS n` rail, driven by `listCollapsed`.

## Verification

Vitest:

- collapse toggles the store and the rail renders the count;
- the width clamps at both ends.

Then look at it: `docker compose --profile web up web`, drag the
splitter to both extremes, collapse and expand.

## Done

- Tests pass.
- `**Status.** Done.` on `### T058a`, in the same commit.

## Files

```
web/src/components/Splitter.tsx
web/src/**/__tests__/**
docs/v1/17-serial-task-plan.md
```

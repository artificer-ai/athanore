# T058a — Splitter, list collapse, CRT chrome

**Task.** `docs/v1/17-serial-task-plan.md` § `### T058a`.
**Specs.** `docs/v1/10-frontend.md` §Chrome; `docs/v1/15-decisions.md`
D36.

## What this task is

The three pieces of chrome that make the shell feel like the mock: a
resizable splitter, a collapsible run list, and the CRT overlay.

## What this task is not

- No content changes. This is chrome only.
- The CRT layer must never intercept input: `pointer-events: none`,
  always.
- Not always-on. It respects `prefers-reduced-motion` and the `crt`
  preference.

## Steps

1. `Splitter` via `react-resizable-panels`: min 260, max
   `window − 340`, a 5 px handle, width persisted to prefs.
2. List collapse to the 30 px `RUNS n` rail, driven by `listCollapsed`.
3. `CrtChrome`: scanlines, scan band, vignette, flicker;
   `pointer-events: none`; disabled under `prefers-reduced-motion` or
   `crt=false`; with a toggle in settings.

## Verification

Vitest:

- collapse toggles the store and the rail renders the count;
- **the chrome is absent when `matchMedia` reports reduced motion** —
  mock `matchMedia`, since jsdom does not implement it;
- the width clamps at both ends.

Then look at it: `docker compose --profile web up web`, drag the
splitter to both extremes, collapse and expand, toggle CRT.

## Done

- Tests pass; the reduced-motion path is asserted, not assumed.
- `**Status.** Done.` on `### T058a`, in the same commit.

## Files

```
web/src/components/{Splitter,CrtChrome}.tsx
web/src/**/__tests__/**
docs/v1/17-serial-task-plan.md
```

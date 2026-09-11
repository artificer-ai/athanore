# Three mobile screens — the global screen beside the list

**Task.** Not a `Txxx` row: operator-requested work after the v1 build
order, amending `docs/plans/Maybe let's do three mobile screens-three-screen-line.md`
(D217), which had read the request as a line with the detail in the
middle. Nothing in `docs/v1/17-serial-task-plan.md` changes and no
`**Status.** Done.` line is added — this file is the scope fence.

**Specs.** `docs/v1/21-design-refresh.md` §Narrow layout (§One
breakpoint, §Regions narrow, §Touch operation, §Gates);
`docs/v1/10-frontend.md` §Layout, §Panes, §Keyboard, §Accessibility and
quality; D194, D216, D217.

## What the operator asked for

Three screens below the breakpoint — the global panes, the workflow
list, the workflow detail. The list loads by default. From the list a
swipe reaches the global panes; from the global panes the same swipe
goes nowhere. The detail is reached only by selecting a run, never by a
swipe; from the detail a swipe goes back to the list. Asked which way
the finger moves, the operator chose **rightward** for both of those
swipes, and confirmed that the reverse swipe on the global screen
returns to the list.

That makes the three screens a row with the list in the middle:

```
global  ◀──swipe right──  list  ──tap a row──▶  detail
global  ──swipe left───▶  list  ◀──swipe right──  detail
```

## What changes from D217

| | D217 | now |
|---|---|---|
| global screen is | `?run=` **and** `?global=` set | `?global=` set, `?run=` **unset** |
| `?global=` beside `?run=` | the global screen over that run | inert; the detail shows |
| `?global=` alone | inert; the list shows | the global screen |
| list: swipe right | nothing | global screen, pane 0 |
| detail: swipe right | global screen | list (`onClearRun`) |
| detail: swipe left | list (`onClearRun`) | nothing |
| global: swipe left | detail | list |
| `global panes` button on | detail, global | list, global |
| global screen's `←` | `back to the run` | `back to runs` |
| `onClearRun` clears `?global=` | yes (screen goes with the run) | yes (a stale index would hijack the `←`) |

Unchanged: `useSwipe`, the overlays, the pane cycle and every key, the
route's other writes, everything at `md` and above.

## Files

```
web/src/App.tsx                               showingGlobal, onSwipe, the footer prop
web/src/routes/AppRoute.tsx                   comments only; onClearRun still clears `global`
web/src/routes/search.ts                      docblock
web/src/panes/PaneBar.tsx                     the global screen's `←` is `back to runs`
web/src/components/Detail.tsx                 docblock
web/src/components/Footer.tsx                 docblock
web/src/components/Splitter.tsx               docblock
web/src/lib/useSwipe.ts                       docblock
web/src/App.test.tsx
web/src/routes/__tests__/AppRoute.test.tsx
web/src/panes/__tests__/PaneBar.test.tsx
web/src/components/__tests__/Detail.test.tsx
web/e2e/mobile.spec.ts                        the sixth flow, as the row
web/e2e/a11y.spec.ts                          the third narrow state opens from the list
web/e2e/support/fixtures.ts                   backToRun() removed
docs/v1/21-design-refresh.md
docs/v1/10-frontend.md
docs/v1/15-decisions.md                       D218
```

## Done

- At 390 px: the list loads by default; a swipe right on it opens the
  global panes; a swipe left on the global screen returns to the list
  and a swipe right there does nothing; a row tap opens the detail; a
  swipe right on the detail returns to the list and a swipe left does
  nothing; no swipe reaches the detail.
- `?global=` is read only while `?run=` is unset; beside a run it is
  inert and `onClearRun` clears it.
- `global panes` is on the list and the global screen; both `←`s read
  `back to runs`.
- Gate green; `tests/snapshots` and `web/src/api/gen` byte-identical.

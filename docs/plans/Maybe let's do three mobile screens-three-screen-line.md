# Maybe let's do three mobile screens — the three narrow screens as one line

**Task.** Not a `Txxx` row: operator-requested work arriving through the
`feature` workflow, after the v1 build order. Nothing in
`docs/v1/17-serial-task-plan.md` changes and no `**Status.** Done.` line
is added — this file is the scope fence instead. It amends the work of
`docs/plans/See global plugins on mobile-narrow-global-screen.md` (D216),
which is the change this one reshapes; read that plan first, because
every file below is one it created or touched.

**Specs.** `docs/v1/21-design-refresh.md` §Narrow layout (§One
breakpoint — the three stacked states and what `?global=` means; §Regions,
narrow — the detail's `←` and the footer's two buttons; §Touch operation
— the six flows, the gesture, and the two "nothing reachable only via"
rules; §Gates — the mobile spec and the axe states);
`docs/v1/10-frontend.md` §Layout (the narrow paragraph), §Panes (the
cycle, the index that is "the operator's attention", the global panes'
own index), §Keyboard (`←`/`→` cycle panes, `b` toggles the list, `esc`
unwinds nearest outwards, the map stays fully bound at every width),
§Accessibility and quality (the mobile spec and the axe states);
`docs/v1/09-plugins.md` §Slots (`global`: "a pane shown when no run is
selected"); D194 (the stacked split rides `?run=`, "no new state"), D197
(`tap()` and CDP touch), D201 (2) (`useIsNarrow()` in exactly three
components), D209 (the desktop's route back to the global panes), D216
(the global screen, all eight items — (1), (3) and (5) are what this
change amends).

## What this change is

D216 made the global panes a third narrow screen that sits **over
either** of the other two: `?global=` set is the global screen whether
`?run=` is set under it or not, a swipe right opens it from the list and
from the detail alike, the bar's `←` is labelled by what is underneath
(`back to the run` / `back to runs`), and a swipe left on the detail does
nothing. The operator likes the panes and finds that shape confusing,
and asked for three screens in a line instead.

This change makes the three narrow screens **one sequence**:

```
list  ──tap a row──▶  detail  ──swipe right──▶  global
list  ◀──swipe left── detail  ◀──swipe left──   global
```

- The **list** is the root. A swipe on it — either way — does nothing;
  a run is chosen by tapping its row, as the operator said.
- The **detail** (the operator's "workflow" screen: the selected run's
  panes) is one step in. A swipe **left** goes back to the list, through
  the same write the bar's `←` makes (`onClearRun`); a swipe **right**
  opens the global screen on its first pane.
- The **global** screen is the far end, and it is always over a run. A
  swipe left goes back to the detail, on the pane of the run the
  operator left (`?run=` and `?pane=` untouched, as D216 has it); a
  swipe right does nothing.

So a swipe left is always *one screen towards the list*, a swipe right
is *one screen away from it*, and only the detail has one to go to.
Every gesture keeps its button: `←` in the bar (`back to runs` on the
detail, `back to the run` on the global screen) and the footer's
`global panes` toggle, which is now drawn on the detail and the global
screen only — the list has no swipe to twin. `esc` keeps unwinding one
rung outwards, which below the breakpoint reads as one screen towards
the list per press.

At `md` and above **nothing changes** in what is drawn. `?global=` is
inert there, as before.

### The brief's five questions, settled

1. **State: `?global=<index>` stays; there is no screen parameter and
   no stack.** The three screens are a total order and the search
   already says which one it is: `?run=` unset is the list, `?run=` set
   is the detail, `?run=` and `?global=` set is the global screen. A
   `?screen=` would be a second copy of `?run=`'s presence that could
   contradict it (`screen=2` with no run), and a stack is the same three
   values written longer. What changes is that **`?global=` is read only
   beside `?run=`**: alone it is inert, kept rather than cleared, exactly
   as it is at `md` and above (D194's rule for `listCollapsed`), and the
   next navigation that names a run clears it as D216 (3) already does.
   The app never writes that state any more, because `onClearRun` now
   clears `?global=` with the run (it amends D216 (3)): the one thing
   under the screen is gone, so the screen over it goes too, and a run
   deleted from the palette while the global screen is up lands on the
   list. A deep link `?run=X` lands on the detail; `?run=X&global=n` on
   the global screen over X; `?run=X&pane=p&global=n` on the global
   screen, with `p` where a swipe left lands; `?global=n` alone on the
   list. The brief's numbering (0 = global, 1 = list, 2 = workflow) is
   not the topology the request's gestures describe — the detail is
   between the other two, which is why the swipe left from it reaches
   the list and the swipe right from it reaches the global panes — and
   is not adopted anywhere.
2. **Gesture scope: read everywhere, acted on by the shell.** The
   listener stays attached to the stacked `<main>` on every narrow
   screen, as `Splitter` does today; "does nothing" is the shell's
   `onSwipe` handler ignoring a direction that has no meaning on the
   screen it is on. Attaching and detaching per screen would buy
   nothing and would re-run the effect on every screen change.
   Overlays are unchanged: they portal out of the region, the listener
   is native, so a finger on a sheet or its backdrop is never read
   (D216 (4)); a swipe under an open overlay is not a thing. Nothing
   about `useSwipe` itself changes.
3. **Keyboard: nothing is rebound.** `←`/`→` and `1`–`9` cycle the panes
   of whatever the middle shows, at every width, as 10 §Keyboard and
   D216 have them; no key advances a screen, because 21 §Narrow layout
   says narrow "adds touch routes and removes none" and a phone with a
   hardware keyboard keeps the desktop's map. `b` stays `toggle list`
   and stays inert below the breakpoint. `esc` keeps its rungs —
   overlay, global screen, held run, selection — which below the
   breakpoint is already global → detail → list, one per press; the
   held-run rung is never narrow. The brief's out-of-scope line ("changes
   to pane cycling") settles this on its own.
4. **Transitions: instant.** The screens are conditional mounts of one
   `<main>`, not a strip that could slide; the design system's only
   motion is the pulse and the caret (10 §Accessibility and quality),
   and an instant swap is also what `prefers-reduced-motion` would ask
   for. No animation, no framework transition, nothing new in CSS.
5. **Selection and focus: the selection clears on the way to the list;
   nothing moves focus.** Below the breakpoint the list *is* `?run=`
   unset (D194, "no new state"), so leaving the detail for the list is
   `onClearRun` whichever way it is done — the swipe writes what the
   `←` already wrote, and the row is not highlighted afterwards. Keeping
   it selected would need a parameter that says "the list, over a
   selection", which is the overlay model the operator asked to leave.
   DOM focus is not managed across a screen change: the element that had
   it unmounts and focus falls to `body`, as it does today with the
   back control, and the keyboard map is bound on the document so `↓`
   selects from there. A swipe is a finger; nothing had focus that the
   finger needs back. The remounted list opens at the top, as it does
   today.

### What writes `?global=` now

| navigation | writes |
|---|---|
| swipe right on the detail, footer button (screen down) | `global: 0` |
| `◀`, `▶`, a dot, `←`/`→`, `1`–`9`, while the screen is up | `global: <index>` |
| swipe left on the global screen, `←` in its bar, footer button (screen up), `esc` | `global: undefined` |
| swipe left on the detail, `←` in its bar, `esc` on the detail | `onClearRun`: `run, node, task, global: undefined` |
| `onSelectRun`, `onOpenNode`, `onFocusStream` | as today, `global: undefined` among them |
| swipe left or right on the list, swipe right on the global screen | nothing |
| `onSelectPane`, every overlay write | unchanged; `?global=` is left alone |

The one new row is `onClearRun`'s; the one removed row is "swipe right
on the list".

## Files and what each does

### 1. `web/src/App.tsx` — the line

- `showingGlobal` gains the run:
  ```ts
  // The global screen is the far end of the narrow line and always over
  // a run: `?global=` is read beside `?run=` and is inert alone, as it
  // is at `md` and above (D217).
  const showingGlobal = narrow && search.run !== undefined && search.global !== undefined
  ```
  Everything keyed on `showingGlobal` — `usePanes`, `pluginScopeRun`,
  the palette's plugin rows, `esc`, `leave`, `stacked` — follows without
  further change; `stacked`'s expression can stay as it is, since
  `showingGlobal` now implies `search.run !== undefined`.
- `onSwipe` becomes the line, keyed on the screen rather than on the
  global flag alone:
  ```ts
  // One screen towards the list on a swipe left, one away from it on a
  // swipe right, and only the detail has one to go to. A direction with
  // no meaning on the screen it lands on is read and dropped: the
  // listener is the stacked middle's and stays attached (D217 (2)).
  onSwipe={(direction) => {
    if (direction === 'right') {
      if (stacked === 'detail') showGlobal(0)
    } else if (stacked === 'global') {
      showGlobal(undefined)
    } else if (stacked === 'detail') {
      onClearRun?.()
    }
  }}
  ```
  Lift `stacked` into a `const` above the JSX so both the prop and the
  handler read one value.
- `leave` is a function now: `leave={showingGlobal ? () => { showGlobal(undefined) } : undefined}`.
- `Footer`'s `global` is passed when `narrow && search.run !== undefined`,
  with the comment saying why the list has none: the button is the
  discoverable twin of the swipe on the screen it is drawn on, and the
  list has no swipe to the global panes (21 §Touch operation's rule cuts
  both ways — a gesture is never the only route, and a screen with no
  gesture needs no button for it).
- Docblocks: the module's narrow paragraph describes the line; the
  `onShowGlobal` prop doc drops "every way off it" in favour of the
  table above; the `esc` comment's last paragraph says the rungs are the
  line below the breakpoint.

### 2. `web/src/routes/AppRoute.tsx` — `onClearRun` clears `?global=`

```ts
void navigate({
  search: (prev) => ({
    ...prev,
    run: undefined,
    node: undefined,
    task: undefined,
    global: undefined,
  }),
})
```
Comment: the global screen is always over a run (D217), so the screen
goes with the thing under it — a run deleted from the palette while it
is up lands on the list, and the narrow `←` and the swipe left that
share this write leave nothing behind. At `md` and above the key is
inert and clearing it is harmless. `onSelectRun`'s comment loses the
sentence about the global screen being over the list; nothing else in
the file changes.

### 3. `web/src/routes/search.ts` — docblock only

The `global` bullet: "read only beside `run` — the global screen is
always over a run — and inert alone, as at `md` and above". No parse
change; the validator keeps the value whatever `run` is, for the same
reason it keeps `listCollapsed`'s cousins: dropping it would make a
phone link opened at another width forget where it was.

### 4. `web/src/panes/PaneBar.tsx` — one label

`PaneLeave` goes. `leave?: (() => void) | undefined`; the global
screen's `←` is `aria-label="back to the run"`, `title="back to the run
(esc)"`, and nothing else about the control changes. Docblock: the
global screen is over a run, always, so the left slot has one label.
`Detail.tsx` re-exports nothing of it, so the type is simply deleted.

### 5. `web/src/components/Detail.tsx` — pass-through

`leave?: (() => void) | undefined`, the import of `PaneLeave` dropped,
the prop doc trimmed to "the narrow global screen's way back".

### 6. `web/src/components/Footer.tsx` — docblock only

The paragraph on `global panes`: drawn on the detail and the global
screen — the two narrow screens the swipe joins — and not on the list,
which has no gesture to twin. The code is unchanged: the shell decides
when to pass the prop (D201 (2)).

### 7. `web/src/components/Splitter.tsx` — docblock only

The `global` paragraph and the `onSwipe` prop doc describe the line:
left is one screen towards the list, right is one away, read on the
stacked `<main>` at every narrow screen and decided by the shell. No
code change.

### 8. `web/src/lib/useSwipe.ts` — docblock only

The opening paragraph names the line rather than "entered by a swipe
right and left by a swipe left". No code change; the recogniser is the
same.

### 9. `web/e2e/support/fixtures.ts` — no change

`back()`, `backToRun()`, `globalPanes()` and `swipe()` already fit: the
detail's `←` is `back to runs`, the global screen's is `back to the
run`, and the two never draw together.

## Documents

- **`docs/v1/21-design-refresh.md` §One breakpoint.** The three bullets
  become the three screens of one line: `?run=` unset → the list;
  `?run=` set → the detail; `?run=` **and** `?global=` set → the global
  screen, over that run (D217). The global-screen paragraph is rewritten
  around "always over a run": `?global=` is read beside `?run=` and
  inert alone, as at `md` and above; `onClearRun` clears it with the
  run; the sentence about a run deleted from the palette leaving the
  operator "on the global screen over the list" becomes "on the list".
- **§Regions, narrow.** *Detail* bullet: on the global screen the left
  slot's `←` is `back to the run`, and that is its only label. *Footer*
  bullet: `global panes` is drawn on the detail and the global screen,
  not on the list — "on every narrow screen" goes, with the reason (the
  button twins the swipe, and the list has none).
- **§Touch operation.** The gesture paragraph is rewritten as the line:
  the three screens in order, a swipe left one screen towards the list
  (detail → list through the same write as `←`; global → the detail on
  the pane it left), a swipe right one screen away (detail → global on
  its first pane), and the three swipes that are read and do nothing —
  either way on the list, right on the global screen. "Nothing else
  swipes — a swipe left on the detail does not go back to the list" is
  replaced; "nothing swipes the pane cycle" stays. The recogniser's
  rules (edges, scrollers, text fields, 60 px at 2:1) stay word for
  word. The sixth flow's wording is right as it is.
- **§Gates.** "CDP `Input.dispatchTouchEvent` for the swipe" → "for the
  swipes". The axe list is right as it is.
- **`docs/v1/10-frontend.md` §Layout,** the narrow paragraph: the third
  screen is "the global panes over that run, while `?global=` is set
  beside it", and the footer's toggle is "beside it on the detail and
  the global screen".
- **§Panes.** Unchanged in substance; "a screen of their own with an
  index of their own" stays. Add "over the selected run" so the
  sentence and 21 agree.
- **§Keyboard.** The `esc` sentence gains a clause: below the
  breakpoint the rungs after the overlay are the three screens, one
  towards the list per press.
- **§Accessibility and quality.** "a CDP touch sequence for the one
  swipe" → "for the swipes".
- **`docs/v1/15-decisions.md`.** One new row, **D217**, dated
  2026-09-11, marked `**new**`, "**The three narrow screens are one
  line — list, detail, global — and the global screen is always over a
  run; amending D216 (1), (3) and (5).**" Items: (1) `?global=` is read
  only beside `?run=` and is inert alone, kept not cleared; no screen
  parameter and no stack, because the search already says which of the
  three it is and a second copy could contradict the first; (2) the
  swipe is one screen towards the list on a left, one away on a right,
  from the detail only; the three meaningless swipes are read by the
  same listener and dropped by the shell, so the listener never
  churns; (3) `onClearRun` clears `?global=` — the screen goes with the
  run under it — so the swipe left and the `←` on the detail share one
  write and a deletion from the global screen lands on the list; (4)
  the footer's `global panes` is drawn on the detail and the global
  screen, not on the list: the button twins the swipe, and the list has
  none; the consequence, stated, is that on a phone the global panes are
  reached through a run — with no runs the inbox has nothing, and a
  plugin's global pane waits for the first run; (5) no key is rebound:
  `←`/`→`/`1`–`9` cycle whatever the middle shows, `b` stays the list
  toggle, `esc` stays one rung outwards, which is the line; (6) no
  transition animation — conditional mounts, the mock's only motion is
  the pulse and the caret, and instant is what reduced motion asks for;
  (7) the selection clears on the way to the list (D194: the list is
  `?run=` unset) and DOM focus is not managed across a screen change;
  (8) the bar's `←` on the global screen has one label, `back to the
  run`, and `PaneLeave` goes. Reason column: D216's overlay shape — the
  global screen over either of the other two, a swipe right from the
  list, a `←` whose label depended on what was underneath, and a swipe
  left on the detail that did nothing — was found confusing by the
  operator, who asked for three screens in a sequence with the detail
  between the list and the global panes.
- **Not** updated: `docs/site/` and `skills/`, for D216's reason — how
  a phone reaches a global pane is a dashboard detail the plugin author
  does not need. `grep` confirms neither mentions the swipe or the
  button.

No wire change: no OpenAPI regeneration, no `web/src/api/gen` churn,
nothing under `athanore/`.

## Tests

- **`web/src/routes/__tests__/AppRoute.test.tsx`** — "leaves the global
  screen where it is when the run under it goes" becomes "takes the
  global screen down with the run": `/?run=aaaa1111&pane=1&global=0`,
  `clear run` → `?pane=1`. The other `global` cases are unchanged.
- **`web/src/panes/__tests__/PaneBar.test.tsx`**, the *over the global
  screen* describe — `leave={onLeave}`; the `back to runs` case is
  deleted; the one-control case asserts `back to the run` and no `back
  to runs`.
- **`web/src/components/__tests__/Detail.test.tsx`** — `leave={onLeave}`
  reaches the bar as `back to the run`.
- **`web/src/App.test.tsx`**, the *below the breakpoint* describe:
  - `shell()` (the list): no `global panes` button in the document; a
    swipe right and a swipe left on the `<main>` call neither
    `onShowGlobal` nor `onClearRun`.
  - `shell({ global: 0 })`: the list, `data-stacked="list"`, no `back to
    runs`, no `global panes` button — `?global=` alone is inert (replaces
    "shows the global panes over nothing").
  - `shell({ run })` (the detail): `global panes` present,
    `aria-pressed="false"`; a swipe right calls `onShowGlobal(0)`; a swipe
    **left calls `onClearRun` once** and not `onShowGlobal`.
  - `shell({ run, global: 1 })`: a swipe left calls
    `onShowGlobal(undefined)`; a swipe right calls nothing; the bar's `←`
    is `back to the run` and `back to runs` is absent; `global panes` is
    `aria-pressed="true"`.
  - The `esc`, keyboard-cycle and `↓` cases stay, the last one on
    `{ run, global: 0 }` rather than `{ global: 0 }`.
  - The `?global=` above the breakpoint describe is unchanged.
- **`web/src/routes/__tests__/search.test.ts`**,
  **`web/src/lib/__tests__/useSwipe.test.tsx`**,
  **`web/src/components/__tests__/Splitter.test.tsx`**,
  **`web/src/components/__tests__/Footer.test.tsx`** — unchanged; nothing
  they cover moves.
- **Playwright, `web/e2e/mobile.spec.ts`**, the sixth-flow test,
  rewritten as the line. On the list, after `submit('probe', TITLE,
  'tap')`: `globalPanes()` has count 0; `swipe('right')` and
  `swipe('left')` each leave `main[data-stacked="list"]` visible and
  `run` absent from the URL. Tap the row, tap `▶` once (pane 2), record
  `pane`. The button: `tappable`, `aria-pressed="false"`, tap → the
  global screen with the assertions as today (inbox body, `INBOX (1/n)`
  label, `run` and `pane` unchanged in the URL, `global=0`, `contained`);
  answer the permission by tapping `allow`; `question` appears. `←`:
  `tappable(backToRun())`, tap → the detail on `(2/n)`, `global` gone.
  The gesture: `swipe('right')` → the global screen; `swipe('left')` →
  the detail on `(2/n)`; `swipe('left')` again → the list, `run` gone
  from the URL, the row visible, `back()` absent; `swipe('right', 8)`
  → the list stays. `noHorizontalScroll` after every step. The docblock
  and the test title say "the line".
- **Playwright, `web/e2e/a11y.spec.ts`** — unchanged; the global-screen
  audit already opens it from the detail.

Lowest layer for each (13 §Pyramid): the route's write in `routes/`, the
label in `panes/`, the wiring — which screen each swipe lands on — in
`App.test.tsx`, and the one browser test, because only a browser can say
a finger walks the three screens and back.

## Verification

```sh
./scripts/test.sh
git diff --exit-code tests/snapshots web/src/api/gen
pnpm -C web exec playwright test mobile.spec.ts a11y.spec.ts inbox.spec.ts --workers=1
```

Then by hand, `./scripts/run.sh` with a queued `probe` run, in devtools
device mode at 390×844 with touch emulation on: on the list, swipe
either way and confirm nothing moves and there is no `global panes`
button; tap a row; swipe left and confirm the list is back with no row
highlighted; tap the row again, `▶` once, swipe right to the inbox,
swipe right again and confirm nothing moves, swipe left back to pane 2,
`←` to the list; delete the run from the palette while on the global
screen and confirm the list shows with no `global=` in the URL; widen
past 768 px with `?run=…&global=0` and confirm the run shows; narrow
again and confirm the global screen comes back.

## Done

- At 390 px the three screens are one line: a swipe left on the detail
  reaches the list, a swipe left on the global screen reaches the
  detail on the pane it left, a swipe right on the detail reaches the
  global panes, and the other three swipes do nothing.
- `?global=` is meaningful only beside `?run=`; `onClearRun` clears it;
  `?global=` alone shows the list.
- The footer's `global panes` is on the detail and the global screen,
  not the list; the global screen's `←` reads `back to the run` only.
- No key is rebound; no transition is animated; at ≥ 768 px the render
  is byte-identical to before.
- 21 §Narrow layout, 10 §Layout, §Panes, §Keyboard, §Accessibility and
  quality updated; D217 recorded.
- Gate green; `tests/snapshots` and `web/src/api/gen` byte-identical.

## Out of scope (from the brief)

No server or API change; no plugin manifest or `window.athanore`
change; nothing at `md` and above beyond `onClearRun` writing an inert
key away; no light mode, PWA or gesture beyond the one horizontal swipe
already read; no change to pane cycling, the request panel or the
global panes' content; no new keycap and no rebinding of `←`/`→`/`b`;
no animation; no parameter beyond `?global=`; no request count on the
footer button (still a possible follow-up, as D216 (5) left it); no
route to the global panes from the list — that is the shape asked for,
and its consequence is recorded in D217 (4) so it can be revisited.

## Files

```
web/src/App.tsx
web/src/routes/AppRoute.tsx
web/src/routes/search.ts                      (docblock)
web/src/panes/PaneBar.tsx
web/src/components/Detail.tsx
web/src/components/Footer.tsx                 (docblock)
web/src/components/Splitter.tsx               (docblock)
web/src/lib/useSwipe.ts                       (docblock)
web/src/App.test.tsx
web/src/routes/__tests__/AppRoute.test.tsx
web/src/panes/__tests__/PaneBar.test.tsx
web/src/components/__tests__/Detail.test.tsx
web/e2e/mobile.spec.ts
docs/v1/21-design-refresh.md
docs/v1/10-frontend.md
docs/v1/15-decisions.md
```

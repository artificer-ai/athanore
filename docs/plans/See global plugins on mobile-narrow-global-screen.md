# See global plugins on mobile — the narrow global screen

**Task.** Not a `Txxx` row: operator-requested work arriving through the
`feature` workflow, after the v1 build order. Nothing in
`docs/v1/17-serial-task-plan.md` changes and no `**Status.** Done.` line
is added — this file is the scope fence instead.

**Specs.** `docs/v1/21-design-refresh.md` §Narrow layout (§One
breakpoint — the two stacked states this adds a third to; §Regions,
narrow — the detail's back control and the footer's palette button;
§Touch operation — the flows and the "nothing reachable only via a
keyboard shortcut" rule; §Gates — the mobile spec and the axe states);
`docs/v1/10-frontend.md` §Layout (the narrow paragraph), §Panes (the
cycle, the index that is "the operator's attention", the clamp),
§Keyboard (`esc` unwinds nearest outwards), §Overlays (why the global
panes cannot be one), §Accessibility and quality; `docs/v1/09-plugins.md`
§Slots (`global`: "a pane shown when no run is selected"), §Context and
scopes, §Builtins are plugins (the inbox is the one global pane every
build has); D194 (the stacked split rides `?run=`), D197 (the pinned
viewport, `tap()`), D201 (2) (`useIsNarrow()` in exactly three
components), D201 (4) (the dots' hit area), D209 (the global panes need
a pointer route; above the breakpoint that is the back control), D210
(`composedPath()` across shadow roots), D176 (3) (an overlay owns the
keyboard).

## What this change is

Below the breakpoint the global panes are **unreachable**. 21 §One
breakpoint gives the narrow middle two states — `?run=` unset is the
run list, `?run=` set is the detail — and the global panes are what the
*detail* shows when no run is selected (09 §Slots), which is the one
combination the narrow shell never draws. D209 gave the desktop a route
back to them; a phone has none: the inbox, and every `slot="global"`
pane a plugin declares, cannot be opened at 390 px by any gesture,
button or key.

This change adds a **third narrow screen, the global screen**: the same
`Detail` — pane bar, `◀ ▶`, dots, pane body — over the global cycle,
exactly as the desktop draws it with nothing selected. It is entered by
a **swipe right** on the middle region or by a **`global panes` button
in the footer**, and left by a **swipe left**, the pane bar's **`←`**,
the same footer button, or **`esc`**. It rides one new search parameter,
`?global=<index>`, which is the global cycle's own pane index and is
present exactly while the screen is up. `?run=` and `?pane=` are not
touched by any of it, so the run the operator was looking at — and the
pane of it they were on — is where a swipe left puts them back.

At `md` and above **nothing changes**: `?global=` is inert there, kept
rather than cleared, the way `listCollapsed` is inert below (D194).

### The five questions the brief left open, settled

1. **A screen of its own, not a stretch of the run's cycle and not an
   overlay.** Not the cycle: 10 §Panes' cycle is the builtins then the
   selected run's own panes, its count is what `1`–`9` and the clamp
   work over, and a global pane belongs to no run — folding them in
   would change the pane count, the jump keys and the meaning of
   `?pane=` at one width only, and a `?run=&pane=` link would open on a
   different pane on a phone than on a desktop. Not an overlay:
   `?overlay=` is one value, and the two things the operator does from
   the global panes both *are* overlays — the palette (the touch route
   to every operator action, 21 §Regions, narrow) and a global-scoped
   plugin action (`?overlay=action`, T070) — so an overlay would close
   the moment either opened. The global screen is a third value of the
   stacked middle, beside the list and the detail (D194), and it is
   `Detail` drawn over `usePanes(undefined, …)`, which is what the
   desktop already draws with nothing selected. There is no second pane
   host and no new component for the panes themselves.
2. **The dots need no new colour.** The global screen has its own cycle,
   drawn by the same `PaneBar` with the same mapping: the inbox is a
   builtin (neutral-800), a plugin's global pane is a plugin's
   (accent-800). Run panes and global panes are never in one row of
   dots, so there is nothing to tell apart.
3. **Both: a swipe, and a button.** The operator asked for the swipe and
   it is the natural gesture — swipe right reveals what sits to the
   left; swipe left puts it away. But 21 §Touch operation's rule is that
   nothing may be reachable only via a keyboard shortcut, and this
   change extends it in the same spirit: nothing is reachable only via a
   gesture either, because a gesture is undiscoverable and a screen
   reader has none. The button is in the footer, beside `palette`,
   because the footer is the one chrome on every narrow screen and
   `palette` is the precedent for a full-height touch target there. The
   swipe is read on the whole middle region, **not from the edge**: the
   left and right edges are the browser's own back/forward gesture on
   iOS Safari and Android Chrome, and an edge swipe would fire both.
4. **A global action stays on the global screen.** It runs through the
   palette as `?overlay=action&action=…` like every plugin action;
   `?global=` is untouched under it, the overlay closes by writing
   `?overlay=` away, and the pane it was about refetches on its
   `refresh_on` names as it does anywhere. Nothing new is decided; the
   screen simply survives the overlay, which is the reason it is a
   screen (1).
5. **The footer button is the indicator.** It is drawn at every narrow
   screen, so a run's detail says the global panes exist. It carries no
   count: the tab title already prefixes the open-request count (10
   §Attention) and the inbox's own header says `⚠ n open`; a badge on
   the button would be a third copy of one number and is not what was
   asked for. Recorded as a possible follow-up, not built.

### What "global" carries, and what writes it

`?global=` is the global cycle's index — `0` is its first pane — and
its presence is what says the screen is up. One parameter carries both
facts because they are one fact: a global pane index with no global
screen means nothing, and a global screen is always on *some* pane. It
is not `?pane=` reused, because 10 §Panes' index is clamped on read and
never rewritten on a selection change, but *is* rewritten by `◀ ▶`; an
operator who cycles to the second global pane and swipes back would
land on the second pane of the run, which is the one thing the brief
asks to preserve. Reopening the screen starts at `0`: the boring choice,
and one link parameter fewer to remember.

| navigation | writes |
|---|---|
| swipe right, footer button (screen down) | `global: 0` |
| `◀`, `▶`, a dot, `←`/`→`, `1`–`9`, while the screen is up | `global: <index>` |
| swipe left, `←` in the pane bar, footer button (screen up), `esc` | `global: undefined` |
| `onSelectRun` (a row tap, `↑`/`↓`/`j`/`k`) | `run: …, node: undefined, global: undefined` |
| `onOpenNode`, `onFocusStream` | as today, plus `global: undefined` |
| `onClearRun`, `onSelectPane`, every overlay write | unchanged; `?global=` is left alone |

`onSelectRun` clears it because selecting a run is, on the desktop, how
the detail stops showing the global panes and starts showing the run's;
the narrow analogue is the same one navigation. `onOpenNode` and
`onFocusStream` name a run pane by index, so they clear it for the same
reason. `onClearRun` leaves it: a run deleted from the palette while the
global screen is up leaves the operator on the global screen with
nothing selected under it, which is a sound state (`?global=` with
`?run=` unset is the global screen over the list).

## Files and what each does

### 1. `web/src/routes/search.ts` — the parameter

`AppSearch` gains `global?: number`, parsed with `asInteger(search['global'], 0)`
exactly as `pane` is and dropped otherwise. Add it to the docblock's
list with one sentence: the narrow global screen's pane index, present
while that screen is up, inert at `md` and above (21 §Narrow layout).

### 2. `web/src/routes/AppRoute.tsx` — the writes

- New prop on `App`, `onShowGlobal: (index: number | undefined) => void`,
  wired as `navigate({ search: (prev) => ({ ...prev, global: index }) })`.
  `undefined` is how the screen is left; the router drops an undefined
  key from the query string as it does for `overlay`.
- `onSelectRun`, `onOpenNode` and `onFocusStream` add `global: undefined`
  to the search they already write, with a comment saying why (the
  table above). Nothing else in the file changes.

### 3. `web/src/lib/useSwipe.ts` — the gesture (new)

```ts
export type SwipeDirection = 'left' | 'right'

/**
 * Read a horizontal swipe on one element, by touch.
 *
 * Returns a callback ref for the element the gesture is read on;
 * `onSwipe` fires once per recognised swipe with the direction the
 * finger moved. `undefined` reads nothing.
 */
export function useSwipe(
  onSwipe: ((direction: SwipeDirection) => void) | undefined,
): (node: HTMLElement | null) => void
```

Shape follows `lib/useElementWidth.ts`: the node is state, not a ref,
so an element that mounts after the component does is still listened
to; one `useEffect` keyed on `[node, onSwipe]` adds three **native**
listeners with `{ passive: true }` — `touchstart`, `touchend`,
`touchcancel` — and removes them on cleanup. Native rather than React's
`onTouchStart`, because React propagates synthetic events through
*portals*: every overlay portals out of the middle region but is still
its React descendant, and a finger on a sheet must not move the screen
under it. Passive, because the region scrolls vertically and a listener
that could `preventDefault` would put every scroll on the slow path.

Recognition, all constants named at the top of the file:

- `touchstart`: ignored unless `event.touches.length === 1`; ignored
  when `clientX` is within `EDGE = 24` px of either side of
  `window.innerWidth` (the browser's back/forward gesture lives there);
  ignored when any node on `event.composedPath()` up to and including
  the listened element is a text field (`HTMLInputElement`,
  `HTMLTextAreaElement`, `HTMLSelectElement`, or `isContentEditable` —
  a horizontal drag in one selects text) or **scrolls horizontally**
  (computed `overflow-x` of `auto` or `scroll` and `scrollWidth >
  clientWidth` — the shadcn table wrapper is `overflow-x-auto`, and a
  finger dragging a wide table sideways is scrolling it). The path is
  walked rather than `closest()` for D210's reason: a plugin's `custom`
  pane is a shadow root and the touch is retargeted to its host.
  Otherwise the start point is recorded.
- `touchend`: with a recorded start, `dx`/`dy` from
  `changedTouches[0]`; recognised iff `|dx| ≥ TRAVEL = 60` px and
  `|dx| ≥ RATIO = 2 × |dy|`. Fires `onSwipe(dx > 0 ? 'right' : 'left')`.
  The start is cleared either way.
- `touchcancel`: clears the start.

No time cap and no velocity: the ratio is what separates a swipe from
a vertical scroll that wandered, and the scroller check is what
separates it from a horizontal one. Nothing here touches
`touch-action`. The deliberate small overlap with `keys/useKeymap.ts`'s
`isTyping` is noted in the docblock — `lib/` sits under `keys/` and does
not import from it.

### 4. `web/src/components/Splitter.tsx` — the third stacked state

- `stacked?: 'list' | 'detail' | 'global' | undefined`. `'global'` draws
  `detail` — the shell hands it a `Detail` over the global cycle — with
  `data-stacked="global"` on the `<main>`, which is the test hook.
- New prop `onSwipe?: ((direction: SwipeDirection) => void) | undefined`,
  attached with `useSwipe` to the stacked `<main>` via its callback ref
  and to nothing else: the gesture is a property of the stacked middle,
  and the desktop split is never listened to. Docblock: one paragraph
  on the global screen and the swipe.

### 5. `web/src/App.tsx` — one pane model, keyed off the screen

```ts
// The narrow global screen: `?global=` set, below the breakpoint. At
// `md` and above the parameter is inert — kept, not cleared — because
// the detail is the global panes there whenever nothing is selected,
// and a phone's link opened on a desktop should show the run it names.
const showingGlobal = narrow && search.global !== undefined
const panes = usePanes(
  showingGlobal ? undefined : search.run,
  showingGlobal
    ? { index: search.global, onChange: (index) => onShowGlobal(index) }
    : { index: search.pane, onChange: onSelectPane },
)
```

One `usePanes`, not two: what the middle shows is what the keyboard
cycles, what the palette's `append log` looks the log pane up in, and
what `Detail` draws, and on the global screen all three should be the
global cycle. `logPane` and `agentPane` come out `-1` there, so `append
log` asks for nothing, which is already what it does with no log pane.

- `stacked={narrow ? (search.global !== undefined ? 'global' : search.run === undefined ? 'list' : 'detail') : undefined}`
  and `onSwipe={(direction) => onShowGlobal(direction === 'right' ? 0 : undefined)}`
  on `Splitter`. A swipe right on the global screen writes `global: 0`
  over an index that may not be `0` — write it only when
  `search.global === undefined`, and a swipe left only when it is set, so
  neither gesture spends a history entry rewriting the same search (the
  guard 10 §Keyboard gives `esc`).
- `Detail` gets `leave={showingGlobal ? { to: search.run === undefined ? 'list' : 'run', onLeave: () => onShowGlobal(undefined) } : undefined}`;
  `onBack={onClearRun}` stays as it is.
- `Footer` gets `global={narrow ? { pressed: showingGlobal, onToggle: () => onShowGlobal(showingGlobal ? undefined : 0) } : undefined}`.
  `App` is one of D201 (2)'s three `useIsNarrow()` components already,
  so the width is decided here and the footer stays a `max-md:` class
  away from knowing.
- `close` (`esc`) gains a rung between the overlay and the held run:
  `if (showingGlobal) { onShowGlobal(undefined); return }`. Nearest
  outwards, as 10 §Keyboard has it; a held run is never narrow, so the
  order between those two is never exercised, but the rung sits where
  it reads right.
- `App`'s prop docblock gains `onShowGlobal`; the module docblock's
  narrow paragraph gains one sentence on the third screen.

### 6. `web/src/components/Detail.tsx` — pass-through

New prop `leave?: { to: 'list' | 'run'; onLeave: () => void } | undefined`,
documented as the narrow global screen's way back (21 §Regions,
narrow), handed to `PaneBar` unchanged. The empty-cycle copy (`no run
selected`) is right on the global screen too — it means the manifest
answered with no global pane at all, which no build with the builtins
has — so it is left alone.

### 7. `web/src/panes/PaneBar.tsx` — the left slot on the global screen

New prop `leave` (same type as above). When it is given the bar is over
the global cycle, and the left slot draws **one** control: `←`, with
`aria-label` and `title` of `back to the run` when `leave.to === 'run'`
and `back to runs` when it is `'list'`, calling `leave.onLeave`, with
the same classes and `TOUCH` hit area as the existing back control.
Neither the selection's back control nor the collapse toggle is drawn
beside it (the screen is narrow-only, and `panes.run` is `undefined`
there anyway). The right slot — `run <id>` and the pill — stays gated
on `panes.runId` and so draws nothing, exactly as the desktop's global
view does. Docblock: one paragraph.

### 8. `web/src/components/Footer.tsx` — the button

New prop `global?: { pressed: boolean; onToggle: () => void } | undefined`.
When given, a second button is drawn to the left of `palette` (inside
the same right-aligned cluster, after the `flex-1` spacer), reading
`global panes`, `aria-pressed={pressed}`, `md:hidden`, the same border,
padding and `max-md:min-h-[24px] max-md:min-w-[24px] max-md:px-[12px]`
classes as `palette`. The shell passes it only when narrow, and the
class hides it above the breakpoint regardless, so a desktop render is
byte-identical to today's. Docblock: a paragraph on why the footer.

### 9. `web/e2e/support/fixtures.ts` — two helpers

- `globalPanes(): Locator` — `getByRole('button', { name: 'global panes' })`.
- `swipe(direction: 'left' | 'right'): Promise<void>` — a real touch
  through CDP, not a synthetic `TouchEvent`: `page.context().newCDPSession(page)`,
  then `Input.dispatchTouchEvent` `touchStart` at `(x0, 500)`, four
  `touchMove`s stepping to `(x1, 500)`, `touchEnd` with no points, where
  `x0`/`x1` are `100 → 300` for `right` and `300 → 100` for `left`
  (both inside the 24 px edges, both 200 px of travel). D197's reason
  applies: a `dispatchEvent` from inside the page would prove the
  handler and nothing about the browser's touch pipeline. The suite is
  Chromium-only (`web/playwright.config.ts`), so CDP is available to
  every test.

## Documents

- **`docs/v1/21-design-refresh.md` §One breakpoint.** The two-bullet
  list becomes three: `?global=` set → the global screen, whichever of
  the other two is under it. Add the paragraph: what the global screen
  is (the detail over the global cycle, as the desktop draws it with
  nothing selected), that `?global=` is that cycle's index and inert at
  `md` and above, and that `?run=` and `?pane=` are untouched by it.
- **§Regions, narrow.** *Detail* bullet: on the global screen the left
  slot's `←` is labelled `back to the run` / `back to runs` and clears
  `?global=`. *Footer* bullet: the footer keeps the palette button
  **and** gains `global panes`, an `aria-pressed` toggle, drawn below the
  breakpoint only.
- **§Touch operation.** A sixth flow: *open the global panes from a
  run's detail, answer what is waiting there, and return to the pane of
  the run they left*. The swipe, in one paragraph: right opens, left
  closes, read on the middle region, not within 24 px of either edge,
  not over a horizontally scrolling element or a text field, 60 px of
  travel at 2:1. And the rule, beside the keyboard one: nothing in
  those flows may be reachable only via a gesture.
- **§Gates.** The mobile spec drives six flows; the axe gate adds the
  global screen at 390×844.
- **`docs/v1/10-frontend.md` §Layout,** the narrow paragraph: one
  sentence naming the third screen and pointing at 21.
- **§Panes.** After the clamp sentence: below the breakpoint the global
  panes are a screen of their own with an index of their own
  (`?global=`), so leaving it lands on the pane of the run the operator
  was on; at `md` and above they are what the detail shows with nothing
  selected, as before.
- **§Keyboard.** The `esc` sentence gains the rung: an open overlay,
  then the narrow global screen, then a run held by `⏎`, then the
  selection.
- **§Accessibility and quality.** The mobile axe state names the global
  screen among what it walks.
- **`docs/v1/15-decisions.md`.** One new row, **D216**, dated
  2026-09-10, marked `**new**`, covering: (1) the global panes are a
  third narrow screen and neither a stretch of the run's cycle nor an
  overlay, with the two reasons from question 1; (2) `?global=<index>`
  is one parameter carrying the screen and its pane, not `?pane=`
  reused, so the run's pane survives a visit; inert at `md` and above,
  kept not cleared (D194's rule); (3) `onSelectRun`, `onOpenNode` and
  `onFocusStream` clear it because each names a run pane, `onClearRun`
  does not; (4) the swipe is read on the middle region by native
  passive listeners, not from the edges (the browser's back gesture),
  not over horizontal scrollers or text fields, 60 px at 2:1, no
  velocity; (5) a gesture is never the only route — the footer button
  is the discoverable one, beside `palette` for the same reason
  `palette` is there, and carries no request count (the tab title and
  the inbox header already do); (6) `esc` leaves the global screen
  before it clears the selection; (7) the e2e swipe is CDP
  `Input.dispatchTouchEvent`, for D197's reason.
- **Not** updated: `docs/site/` and `skills/`. The site's plugins guide
  says a global panel shows "globally when no run is selected", which is
  the model at every width; how a phone reaches it is a dashboard
  detail the plugin author does not need, and D215 would have the
  skills republished for a sentence.

No wire change: no OpenAPI regeneration, no `web/src/api/gen` churn,
nothing under `athanore/`.

## Tests

- **`web/src/routes/__tests__/search.test.ts`** — `global` is kept as an
  index (`0`, `'2'`), dropped when negative, fractional or not a number.
- **`web/src/routes/__tests__/AppRoute.test.tsx`** — `onShowGlobal(1)`
  writes `?global=1` and leaves `?run=`/`?pane=` alone; `onShowGlobal(undefined)`
  writes it away; `onSelectRun`, `onOpenNode` and `onFocusStream` each
  clear it; `onClearRun` and `onSelectPane` each leave it.
- **`web/src/lib/__tests__/useSwipe.test.tsx`** — a component that
  renders a `<div>` under the hook, driven with
  `fireEvent.touchStart(el, { touches: [{ clientX, clientY }] })` /
  `touchEnd(el, { changedTouches: [...] })` (jsdom's `TouchEventInit`
  takes plain objects, `web/node_modules/jsdom/lib/generated/idl/TouchEventInit.js`):
  120 px right → `'right'`; 120 px left → `'left'`; 40 px → nothing;
  80 px across with 60 px down → nothing; a start at `clientX: 10` and
  at `innerWidth − 10` → nothing; a start inside an `<input>` →
  nothing; a start inside an element with `style.overflowX = 'auto'` and
  `scrollWidth`/`clientWidth` defined as 800/300 → nothing, and the same
  element with `scrollWidth === clientWidth` → recognised; two touches →
  nothing; `touchcancel` then `touchend` → nothing; `onSwipe` undefined
  → no listener (a spy on `addEventListener`). `narrowViewport()` from
  `lib/__tests__/fixtures.ts` sets `innerWidth` for the edge cases.
- **`web/src/components/__tests__/Splitter.test.tsx`** — `stacked="global"`
  draws the `detail` slot and `data-stacked="global"`; a swipe on the
  stacked `<main>` calls `onSwipe('right')`; no listener is attached in
  the split layout.
- **`web/src/components/__tests__/Footer.test.tsx`** — no `global` prop,
  no button; with it, `global panes` carries `aria-pressed` as given,
  calls `onToggle`, and carries `md:hidden`; the palette test still
  finds `/palette/` by role.
- **`web/src/panes/__tests__/PaneBar.test.tsx`** — a `leave` describe:
  `to: 'run'` draws `back to the run`, `to: 'list'` draws `back to
  runs`, pressing it calls `onLeave`; no collapse toggle and no
  selection back control beside it; no `run` and no pill on the right.
- **`web/src/components/__tests__/Detail.test.tsx`** — `leave` reaches
  the bar.
- **`web/src/App.test.tsx`**, the *below the breakpoint* describe, with
  a `slot: 'global'` pane added to `MANIFEST` (an `inbox` on `_builtin`,
  `kind: 'custom'`, `element: 'ath-requests'`, `scope: 'global'` — the
  fixture in `panes/__tests__/fixtures.ts` has the shape) and the
  `shell()` helper accepting `onShowGlobal`:
  `{ run, global: 0 }` shows the detail region with `data-stacked="global"`,
  pane label `INBOX (1/1)`, no `selected-run`, the back control
  `back to the run`; `{ global: 0 }` alone shows it over nothing with
  `back to runs`; the footer's `global panes` is `aria-pressed="false"`
  on the detail and calls `onShowGlobal(0)`, `"true"` on the global
  screen and calls `onShowGlobal(undefined)`; `←` in the bar calls
  `onShowGlobal(undefined)`; `esc` on the global screen calls
  `onShowGlobal(undefined)` and **not** `onClearRun`, and with an
  overlay up closes the overlay instead; `→` on the global screen calls
  `onShowGlobal(…)` and never `onSelectPane`; `↓` still selects and the
  route's write is what clears the screen (asserted at the route). At
  the desktop width: `{ run, global: 0 }` shows the run's panes
  (`OVERVIEW (1/3)`), no `global panes` button is in the document at all
  (the shell passes the prop only when narrow), and `esc` goes straight
  to `onClearRun`.
- **Playwright, `web/e2e/mobile.spec.ts`** — one new test, *the sixth
  touch flow: the global panes*: submit `probe` by tap (its permission
  request lands in the inbox); tap the row; tap `▶` once so the run is
  on pane 2; `tappable(dashboard.globalPanes())`, tap it; expect
  `[data-stacked="global"]`, `pane-inbox` visible, the pane label
  `INBOX (1/1)`, the URL still carrying `run=` and now `global=0`,
  `contained` and `noHorizontalScroll`; answer the permission by tapping
  `allow` (the controls work from here); `tappable` the `back to the
  run` control and tap it; expect the detail with the label back on
  `(2/n)` and `global` gone from the URL. Then the gesture:
  `dashboard.swipe('right')` → the global screen; `swipe('left')` →
  the detail, still on pane 2; tap `back to runs` → the list;
  `swipe('right')` → the global screen over the list, `back to runs`
  in its bar; `swipe('left')` → the list. Finally a swipe that starts
  at `x = 8` leaves the list where it is. Every step ends with
  `noHorizontalScroll`.
- **Playwright, `web/e2e/a11y.spec.ts`**, the *on a phone* describe —
  after the detail audit, tap `global panes` and audit the global
  screen: `blocking` empty, score ≥ floor.

Lowest layer for each (13 §Pyramid): the parse in `routes/`, the
recogniser in `lib/`, the drawing in `panes/` and `components/`, the
wiring in `App.test.tsx`, and one browser test — because only a browser
can say a finger on a phone reaches the inbox and comes back.

## Verification

```sh
./scripts/test.sh
git diff --exit-code tests/snapshots web/src/api/gen
pnpm -C web exec playwright test mobile.spec.ts a11y.spec.ts inbox.spec.ts --workers=1
```

Then by hand, `./scripts/run.sh` with a queued `probe` run, in devtools
device mode at 390×844 with touch emulation on: swipe right on the
list, on the detail, on the inbox itself; swipe left from each; drag a
wide table sideways in a plugin pane and confirm it scrolls rather than
flipping the screen; scroll a long log pane vertically with a slightly
diagonal finger and confirm nothing flips; open the palette from the
global screen and run a command; widen past 768 px with `?global=0` in
the URL and confirm the run is what shows; narrow again and confirm the
global screen comes back. On a real iPhone if one is to hand: an edge
swipe goes back in history and nothing else.

## Done

- At 390 px, from a run's detail and from the list, the global panes
  open by a swipe right and by the footer's `global panes` button, their
  controls work in place, and a swipe left, the bar's `←`, the button
  or `esc` returns to the pane of the run that was under them.
- `?run=` and `?pane=` are byte-identical across a visit; `?global=` is
  present exactly while the screen is up and inert at `md` and above.
- At ≥ 768 px: pixel-identical to before the change.
- The mobile spec's sixth flow and the global-screen axe state pass.
- 21 §Narrow layout, 10 §Layout, §Panes, §Keyboard, §Accessibility and
  quality updated; D216 recorded.
- Gate green; `tests/snapshots` and `web/src/api/gen` byte-identical.

## Out of scope (from the brief)

No change to the plugin system, scopes or `PluginContext`; no builtin
panel change and no new capability; no desktop behaviour — the footer
button is `md:hidden` and `?global=` is inert there; no keycap is added
(`esc` gains a rung, `←`/`→`/`1`–`9` cycle whatever the middle shows,
as they already do); no gesture beyond this one pair — a swipe left on
the detail does not go back to the list, and nothing swipes the pane
cycle; no settings or theme change; no request count on the button.

## Files

```
web/src/routes/search.ts
web/src/routes/AppRoute.tsx
web/src/lib/useSwipe.ts                       (new)
web/src/components/Splitter.tsx
web/src/App.tsx
web/src/components/Detail.tsx
web/src/panes/PaneBar.tsx
web/src/components/Footer.tsx
web/src/routes/__tests__/search.test.ts
web/src/routes/__tests__/AppRoute.test.tsx
web/src/lib/__tests__/useSwipe.test.tsx       (new)
web/src/components/__tests__/Splitter.test.tsx
web/src/components/__tests__/Footer.test.tsx
web/src/panes/__tests__/PaneBar.test.tsx
web/src/components/__tests__/Detail.test.tsx
web/src/App.test.tsx
web/e2e/support/fixtures.ts
web/e2e/mobile.spec.ts
web/e2e/a11y.spec.ts
docs/v1/21-design-refresh.md
docs/v1/10-frontend.md
docs/v1/15-decisions.md
```

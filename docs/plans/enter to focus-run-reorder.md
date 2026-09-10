# enter to focus — `⏎` picks a run up, `↑`/`↓` move it

**Task.** Not a `Txxx` row: this is operator-requested work arriving
through the `feature` workflow, after the v1 build order. Nothing in
`docs/v1/17-serial-task-plan.md` changes and no `**Status.** Done.` line
is added — this file is the scope fence instead.

**Specs.** `docs/v1/10-frontend.md` §Keyboard (the map, exhaustive, and
the `tab` paragraph), §Layout (the run list's selected row and its
footer strip), §Accessibility and quality (colour is never the only
signal; the axe floor); `docs/v1/08-api.md` §Runs
(`POST /api/runs/{id}/position` — `{direction: -1 | 1}` swaps with the
neighbour, a no-op at the ends is still 200 with the current position);
`docs/v1/21-design-refresh.md` §Narrow layout (the list footer's hints
below the breakpoint); D176 (what T067 decided about the map — (1)
`tab` is the browser's, (4) the map dispatches on the palette's key
column, (5) `⏎` is scoped to the run list and cancels the keystroke),
D175 (5) (`reorder` is two keyless palette rows), D194 (the narrow
stack), D178/D179 (the axe floor).

## What this change is

`⏎` on the highlighted run **focuses** it: the row changes colour and
`↑`/`↓` (and `j`/`k`) stop moving the selection and start moving the run
in the dispatch order, one swap per press, through the endpoint the
palette's two keyless rows already call. `⏎` again or `esc` puts it
down. This replaces `⏎ focus detail`, which goes away with the ref and
the `tabIndex={-1}` that served it — `tab` is how the detail pane is
reached, and always was (D176 (1)).

No new keycap is invented, so the map's caps are exactly 10 §Keyboard's
today and after: `⏎`, `↑`, `↓`, `j`, `k` and `esc` are all already in
it. What changes is what two of them mean while a run is held, and 10
§Keyboard is edited to say so.

### The three questions the brief left open, settled

1. **The focused row is visually its own state, not a stronger
   selection.** The design mock has no focused row, so this is the
   boring choice from the tokens it does have: selection keeps the
   mock's blurple (`color-mix(accent 12%, surface)` + 2 px
   `--color-accent` left border); focus draws the *second* accent
   (`color-mix(accent-2 22%, surface)` + 2 px `--color-accent-2-400`
   left border, same width so no column shifts). Colour is not the only
   signal: the list's footer strip swaps its hints (below).
2. **Selection follows the run, because selection *is* the run.**
   `?run=` names an id, not a row index; the row moves, the id does
   not, and React keys the rows by `row.id`, so the DOM node — and the
   browser focus on it, if the operator clicked the row — travels with
   it. Nothing in the shell writes `?run=` on a move.
3. **A run can only be focused while it is the selected run**, while
   its row is in the list on screen, and only at `md` and above. Focus
   is entered from the selection and cannot outlive it: changing the
   selection, filtering the row away, deleting the run or narrowing the
   window past the breakpoint all put it down. That is what keeps the
   arrow keys from moving a run nobody can see.

## Files and what each does

### 1. `web/src/store/ui.ts` — the state

Add, beside `focus` / `logComposerFor`, which are the same kind of fact
(client state, deliberately not persisted and not in the URL):

```ts
/** The run `⏎` has picked up, or `null` (10 §Keyboard). */
focusedRun: string | null
/** `⏎`: pick this run up. */
focusRun: (runId: string) => void
/** `⏎` again, `esc`, or the row leaving the screen: put it down. */
blurRun: () => void
```

It holds the id and not a boolean so the shell can say *which* run is
held and check it against the selection; the store knows nothing about
`?run=` and does no clearing of its own. Extend the module docblock with
one sentence saying why it lives here.

Do not touch `focus` / `setFocus` / `toggleFocus`: the two regions still
follow the browser through `onFocusCapture`, and that is unrelated to
this.

### 2. `web/src/keys/useKeymap.ts` — the map

`KeymapHandlers`:

- **remove** `focusDetail`.
- **add** `runFocused: boolean` — the one piece of state the table has
  to dispatch on, handed in like `actions` is.
- **add** `toggleRunFocus: () => void` (`⏎`) and
  `moveRun: (delta: -1 | 1) => void` (`↑`/`↓`/`j`/`k`, while held).

`handleKey`:

- `ArrowDown` / `j`: `preventDefault`, then
  `handlers.runFocused ? handlers.moveRun(1) : handlers.select(1)`.
  `ArrowUp` / `k`: the same with `-1`.
- `Enter`: unchanged scope and cancellation — `if (!inList(...)) return
  false`, `preventDefault`, then `handlers.toggleRunFocus()`. D176 (5)'s
  reason for cancelling still holds: a row is a `<button>` and an
  uncancelled `⏎` would click it.
- `esc`: unchanged. It calls `handlers.close()`, and the shell decides
  what "close" is (below).

Everything else in the map keeps working while a run is held: only
`↑`/`↓`/`j`/`k` change meaning. The reorder arrows are **not** scoped to
the list region, exactly as `select` is not: the mode is explicit and
visible, and the pair they replace fires from anywhere the plain keys
apply. `⏎` keeps its list scope, because that is where a run is picked
up from; `esc` puts one down from anywhere, as `esc` always has.

Rewrite the module docblock's opening sentence (it transcribes 10
§Keyboard) and the `inList` docblock (it explains `⏎ focus detail`).

### 3. `web/src/App.tsx` — the wiring

- Read `focusedRun`, `focusRun`, `blurRun` off `useUi`; drop the
  `setFocus` read and the `detail` ref.
- Derive, in render:

  ```ts
  const runFocused =
    focusedRun !== null &&
    focusedRun === search.run &&
    !narrow &&
    runs.rows.some((row) => row.id === focusedRun)
  ```

  and one effect that puts a run down once that stops being true —
  `useEffect(() => { if (focusedRun !== null && !runFocused) blurRun() },
  [focusedRun, runFocused, blurRun])`. The derived value is what the
  render and the keys use, so the frame before the effect commits is
  never drawn wrong; the effect is the housekeeping that stops a stale
  id springing back when the operator re-selects that run later.
- Keymap handlers:

  ```ts
  runFocused,
  toggleRunFocus: () => {
    if (narrow || search.run === undefined) return
    if (runFocused) blurRun()
    else focusRun(search.run)
  },
  moveRun: (delta) => {
    if (!runFocused || search.run === undefined) return
    runOps.reorder(search.run, delta < 0 ? 'up' : 'down')
  },
  close: () => {
    if (search.overlay !== undefined) {
      onCloseOverlay?.()
      return
    }
    if (runFocused) blurRun()
  },
  ```

  `close` takes the overlay first: it is the nearer thing, and while one
  is up the arrows are suppressed anyway (`keyboardOwned()`).
- Pass the state down: `<RunList … focusedRun={runFocused ? search.run
  : undefined} />`.
- The palette's `reorder` row is untouched and stays keyless (D175 (5)):
  `↑`/`↓` are not a palette command — no palette row can be a mode — and
  the two rows still print `—`.

### 4. `web/src/components/Detail.tsx` — what `⏎` leaves behind

Nothing focuses the region programmatically any more, so remove the
`ref` prop, the `Ref` import, `tabIndex={-1}` and the
`focus:outline-none` that went with it, and the docblock sentence about
`⏎ focus detail`. Keep `data-region`, `data-focused`, the mousedown /
focus-capture handlers and the border treatment: the region still
follows the browser's focus, which is now the only thing that moves it.

### 5. `web/src/components/RunList/RunList.tsx` — the drawing

- New prop `focusedRun?: string | undefined`; `const focused =
  focusedRun !== undefined` for the strip, `row.id === focusedRun` per
  row.
- `RowProps` gains `focused: boolean`; both `Row` and `NarrowRow` take
  it (one component, one prop — the narrow row will never receive
  `true`, and hard-coding that in two places is how the two shapes drift).
- `rowClasses(zebra, selected, focused)`: focused replaces the selected
  pair with `border-l-[var(--color-accent-2-400)]` and
  `bg-[color-mix(in_srgb,var(--color-accent-2)_22%,var(--color-surface))]`.
  A focused row is always a selected row, so the two never both apply;
  write it as `focused ? … : selected && …` so tailwind-merge is not
  asked to pick.
- `data-run-focused={focused}` on the row button, beside
  `data-selected`. It is a `data-*` attribute and not ARIA: `option`
  takes `aria-selected` and nothing else that means this, and
  `aria-grabbed` is deprecated. The row keeps `aria-selected`.
- The muted columns read `selected || focused` for their one step of
  extra contrast (10 §Accessibility and quality).
- The footer strip's two hints become one `role="status"` wrapper
  (`<span role="status" className="flex gap-[14px] max-md:hidden">`)
  holding them, so the mode change is announced as well as drawn:

  | | first hint | second hint |
  |---|---|---|
  | idle | `↑↓ select` | `⏎ focus run` |
  | focused | `↑↓ move run` | `⏎/esc done` |

  `n shown` stays outside the wrapper and outside the live region. The
  strip is `max-md:hidden` as it already is, which is consistent: there
  is no focus mode below the breakpoint.

### 6. `web/src/lib/keys.ts` — the one table the map, the footer and `?` share

- The `focus-detail` row becomes `focus-run`: `keys: ['⏎']`, `label:
  'focus run'`.
- A new row in `navigate`, straight after `select`: `id: 'move-run'`,
  `keys: ['↑', '↓', 'j', 'k']`, `label: 'move run'`, `note: 'while a run
  is focused'`, `footer: false`. Four caps and not two, because
  `lib/keys.ts` draws `↑`/`↓`/`j`/`k` as one binding — "one thing the
  operator can do" — and `j`/`k` moving a held run is what keeps that
  true.
- A third `KEY_NOTES` line: "`⏎` picks the selected run up; `↑`/`↓` then
  move it in the dispatch list, and `⏎` or `esc` puts it down".

The footer strip's chips are the `footer: true` rows and do not change;
the `?` overlay gains the new row and the relabelled one for free.

### 7. `web/src/overlays/runOps.ts` — one line

The reorder toast gets a stable id per run (`run-position-${runId}`) so
that holding `↓` replaces one toast rather than stacking eight. Thread
it as an optional third argument to the local `settle` helper; the other
four operations are untouched, and the palette's rows get the same
improvement for free. Nothing else here changes: the call, the `{direction}`
body, the invalidations and the "report the position the server settled
on" note are all already right.

**The swap is against the true dispatch neighbour, which a header filter
may be hiding.** `{direction: -1}` swaps with the run above in
`position` order over the whole table (`store/repos/runs.py`
§`swap_position`), not with the row above on screen. Under an active
chip or `/` filter, a press can therefore move the run past a run the
operator cannot see, and the visible order may not change. That is
accepted: the toast reports the position the server settled on, which is
the honest report (02 §Real data only), and the alternative — computing
`{index}` from the visible neighbour — would make one key mean two
different moves depending on a filter. The endpoint is not touched
either way (brief, out of scope).

No optimistic reordering and no debounce: `settle` invalidates
`queryKeys.runs()` and the list redraws from the server, and each press
posts a swap the server resolves against the row's current position, so
presses that arrive faster than the refetch are still each correct.

## Documents

- **`docs/v1/10-frontend.md` §Keyboard.** Replace `⏎` focus detail with
  `⏎` focus run in the map sentence. Replace the last clause of the
  `tab` paragraph ("and `⏎` is what sends attention to the detail
  pane") — `tab` is now the only way to the detail pane, which is what
  that paragraph argued for in the first place. Add a paragraph after
  it: what focus mode is, that `↑`/`↓` and `j`/`k` move the run through
  `POST /api/runs/{id}/position` `{direction: -1 | 1}`, that `⏎` again
  or `esc` leaves, that focus is only ever on the selected run, only
  while its row is on screen, and only at `md` and above, and that the
  rest of the map is unaffected while a run is held.
- **`docs/v1/10-frontend.md` §Layout.** The run-list bullet gains the
  focused row's tint and border and the strip's two states.
- **`docs/v1/21-design-refresh.md` §Narrow layout.** The quoted hint
  becomes `↑↓ select · ⏎ focus run`; add that there is no focus mode
  below the breakpoint, because the list is not on screen while a run is
  selected (D194).
- **`docs/v1/15-decisions.md`.** One new row, **D204**, dated
  2026-09-10, marked `**new**`, covering: (1) `⏎` is focus run and the
  detail pane's ref and `tabIndex` go with the old binding, `tab` being
  the way there (D176 (1)); (2) focus is a fact about the *selected*
  run — id in `useUi`, read as held only while it is `?run=`, its row is
  in the filtered list and the viewport is at `md` or above, so a
  filter, a delete or a narrow window cannot leave an invisible run
  under the arrows; (3) `j`/`k` move too, because the table draws the
  four caps as one binding; (4) the swap is the endpoint's `{direction}`
  against the true dispatch neighbour, filter or no filter, with
  `{index}` from the visible neighbour considered and rejected; (5) the
  focused row is the second accent at 22 % with an accent-2 left border
  and the list's footer strip swaps its hints inside a `role="status"`
  wrapper, so the mode is announced and is not colour alone — the mock
  has no focused row, so this is the boring choice from its tokens; (6)
  `esc` puts a run down only when no overlay is up, the overlay being
  the nearer thing.
- **Not** updated: `docs/v1/17-serial-task-plan.md` § T061 and
  `docs/plans/T061-run-list.md` quote the old strip. They are the record
  of what that task shipped, and 10 is the document that specifies the
  behaviour.

No wire change: no OpenAPI regeneration, no `web/src/api/gen` churn.

## Tests

- **`web/src/store/__tests__/ui.test.ts`** — `focusedRun` starts `null`;
  `focusRun` / `blurRun`; a second `focusRun` replaces the first; still
  nothing reaches `localStorage`.
- **`web/src/keys/__tests__/useKeymap.test.tsx`** — the `⏎` describe
  becomes focus run: it toggles from the list's chrome, from a row (and
  cancels the keystroke), and from the page itself; it does nothing from
  the request panel. A new describe for the mode: with `runFocused:
  true`, each of `ArrowUp`/`k` and `ArrowDown`/`j` calls `moveRun(-1)` /
  `moveRun(1)` and never `select`; with it `false`, they select and
  never move; while typing in the `/` input and while an overlay owns
  the keyboard, they do neither. Update the `handlers()` spies
  (`focusDetail` out; `toggleRunFocus`, `moveRun` in; `runFocused` on
  the mounted keymap).
- **`web/src/components/__tests__/RequestPanel.test.tsx`** — its
  `underTheKeymap` harness builds a `KeymapHandlers` literal; update it
  to the new shape (typecheck will point at it).
- **`web/src/components/RunList/__tests__/RunList.test.tsx`** — the
  focused row carries `data-run-focused="true"` and is still
  `aria-selected`, the other rows do not; the strip reads `↑↓ select` /
  `⏎ focus run` idle and `↑↓ move run` / `⏎/esc done` focused, with the
  focused pair inside a `role="status"` element.
- **`web/src/App.test.tsx`** — replace "hands the keyboard to the detail
  pane on `⏎`" with the shell's half of this feature, reusing the
  existing `posted()` fetch harness from the run-operations describe:
  `⏎` on a selected run sets `focusedRun` and marks the row; `↑` then
  posts `/api/runs/aaaa1111bbbb/position` and calls `onSelectRun` not at
  all; `⏎` again and `esc` each put it down (and `esc` with no overlay
  still navigates nowhere); `⏎` with no run selected posts nothing and
  focuses nothing; selecting another run, and rendering narrow
  (`narrowViewport()`), each put a held run down. Keep the "binds every
  keycap of `lib/keys.ts`" test passing — the new row's caps are all in
  its `navigation` set already.
- **`web/src/lib/__tests__/keys.test.ts`** — update the quoted `SPEC`
  string to 10 §Keyboard's new sentence. Both directions of the
  keycap check must still pass: the caps are unchanged, only a label and
  a row are.
- **Playwright, `web/e2e/queue.spec.ts`** — a second test beside the
  palette one: submit three `hold` runs, `select('third')`, press
  `Enter`, expect that row to carry `data-run-focused="true"`; press
  `ArrowUp` and expect `titles()` to poll to `['first', 'third',
  'second']` with the row still `aria-selected` and still focused; press
  `Escape` and expect the attribute to go false; press `ArrowUp` again
  and expect the *selection* to move and `titles()` to be unchanged.
  That last assertion is the one that proves the mode is a mode.

Lowest layer that can express the behaviour (13 §Pyramid): the table in
`keys/`, the drawing in `RunList/`, the wiring in `App.test.tsx`, and
exactly one browser test — because only a browser can say the keystroke
reaches the endpoint and the list comes back reordered.

## Verification

```sh
./scripts/test.sh
git diff --exit-code tests/snapshots web/src/api/gen
pnpm -C web exec playwright test queue.spec.ts keyboard.spec.ts a11y.spec.ts --workers=1
```

Then by hand, `./scripts/run.sh` with a few queued runs: `⏎` on the
highlighted run, hold `↓` to the bottom and `↑` back to the top, watch
the toast replace itself rather than stack; `esc`; `⏎` again; `⏎` with
nothing selected; type in the `/` filter until the held row is gone and
confirm the mode drops; drag the window under 768 px while a run is
held. Check the focused tint against the selected one at both ends of
the type ramp.

## Done

- `⏎` on the highlighted run focuses it; `↑`/`↓` and `j`/`k` move it one
  place per press through `POST /api/runs/{id}/position`; `⏎` or `esc`
  leaves; selection never moves while a run is held.
- The focused row is drawn in the second accent and the list's footer
  strip says which mode it is in, in a live region.
- `focusDetail` is gone from the tree, with the `Detail` ref and
  `tabIndex` that served it.
- The map, the footer chips, the `?` overlay, `lib/keys.ts` and 10
  §Keyboard all say `⏎ focus run` and agree with each other.
- 10 §Keyboard, 10 §Layout and 21 §Narrow layout updated; D204 recorded.
- Gate green; `tests/snapshots` and `web/src/api/gen` byte-identical.

## Out of scope (from the brief)

`tab` stays the browser's (D176 (1)). No touch or narrow-viewport
equivalent — the mock has none and the list is not on screen there. No
key for the palette's two `reorder` rows, which stay keyless (D175 (5)).
No change to `POST /api/runs/{id}/position`, its body, or any event.

## Files

```
web/src/store/ui.ts
web/src/keys/useKeymap.ts
web/src/App.tsx
web/src/components/Detail.tsx
web/src/components/RunList/RunList.tsx
web/src/lib/keys.ts
web/src/overlays/runOps.ts
web/src/store/__tests__/ui.test.ts
web/src/keys/__tests__/useKeymap.test.tsx
web/src/components/__tests__/RequestPanel.test.tsx
web/src/components/RunList/__tests__/RunList.test.tsx
web/src/lib/__tests__/keys.test.ts
web/src/App.test.tsx
web/e2e/queue.spec.ts
docs/v1/10-frontend.md
docs/v1/21-design-refresh.md
docs/v1/15-decisions.md
```

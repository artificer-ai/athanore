# T082 — Mobile support

**Task.** `docs/v1/17-serial-task-plan.md` § `### T082`.
**Specs.** `docs/v1/21-design-refresh.md` §Narrow layout, §Touch
operation and §Gates (normative — the breakpoint, the regions, the
narrow treatments, the overlay rules, the five flows and the three axe
states); `docs/v1/10-frontend.md` §Layout, §Overlays, §Accessibility
and quality (the sections this updates; the desktop layout that must
not change); D194 (the stacked split), D197 (the pinned viewport and
`tap()`), D178 (the axe floor).

## What this task is

Mobile support, whole: below one breakpoint the shell stacks, every
region and overlay gets its narrow treatment, and CI proves the
dashboard usable end to end on a phone by touch alone. At `md` and
above **nothing changes** — diffing a desktop screenshot before/after
this task should show pixels identical.

### The shell (below `md`, 768 px)

1. **The stacked split** (`App.tsx`, `Splitter.tsx`). Below `md` the
   splitter/rail is not mounted; the middle is the run list while
   `?run=` is unset and `Detail` while it is set. Selection already
   lives in the search params, so this is a render decision, not new
   state. `listWidth` / `listCollapsed` are left untouched (inert, not
   cleared). Prefer Tailwind `md:` classes; where a component must
   *know* (mount one subtree or the other), a small `useIsNarrow()`
   matchMedia hook — one definition, `(min-width: 768px)`, not a
   scattered constant.
2. **Back control** (`panes/PaneBar.tsx`). Below `md` the left slot
   renders `←` with `aria-label="back to runs"` instead of the
   list-collapse toggle; it clears `?run=` through the same search-write
   path selection uses. Hit area ≥ 24×24 px.
3. **Run list rows** (`components/RunList/RunList.tsx`). Below `md` the
   six-column grid becomes the two-line row of 21 §Narrow layout:
   line 1 TITLE (run id when untitled) + STATUS pill; line 2
   `run id · workflow · node · age` in `text-meta`, keeping the `⚠`
   glyph beside the node. Same `RunSummary`, same selection handler.
   The list footer keeps `n shown`, hides `↑↓ select · ⏎ focus detail`.
4. **Header** (`components/Header.tsx`). Below `md`: two rows — the
   brand/version/counts and the two buttons; then the chips
   (`RunFilters`) and the `/` filter as one horizontally scrollable
   strip (`overflow-x-auto`, its own scrollbar hidden but scrollable —
   the *page* must not scroll horizontally). `＋ new run`, `workflows`
   and T081's text-size button stay visible, ≥ 24×24 px hit areas.
5. **Footer** (`components/Footer.tsx`). Below `md` the key-hint chips
   are hidden; the palette button remains, relabelled `palette`, as a
   full-height touch target.
6. **Keyboard.** No change: the map stays bound at every width.

### The overlays (below `md`)

7. **Shared surface** (`overlays/OverlayPanel.tsx` and the dialogs that
   roll their own root — D176 (3) names them): cap panel width to the
   viewport minus the backdrop margin and height to `100dvh` minus the
   same; content scrolls inside the panel, never the page.
8. **Palette** (`Palette.tsx`): full-width under the header; rows are
   ≥ 24 px touch targets.
9. **New run / edit** (`NewRun.tsx`, `EditRun.tsx`): span the width;
   the workflow chip group wraps; with the form empty, `submit run` and
   `cancel` are visible without scrolling.
10. **Library** (`Library.tsx`): full-screen sheet, columns stacked —
    list above, source viewer below.
11. **Task drawer** (`TaskDrawer.tsx`): full-screen sheet.
12. **Pickers, keys, delete, action** (`Pickers.tsx`, `Keys.tsx`,
    `DeleteRun.tsx`, `PluginAction.tsx`): sized to fit; the keys overlay
    keeps its desktop content but scrolls and closes by touch.
13. **Touch close**: every overlay closes on backdrop tap (Radix default
    — verify none of the dialogs suppress it) and any overlay header's
    close affordance is a real button.

### The gates

14. **`web/e2e/mobile.spec.ts`** (new), 390×844, `hasTouch`,
    `isMobile`, every activation `tap()`, on the `probe` fixture
    workflow: the five flows of 21 §Touch operation end to end —
    view the list; open the run (detail fills the width, tap back, the
    list returns); cycle panes with the pane bar's `▶` (assert the pane
    label advances and wraps); answer the open permission request by
    tapping its option button (assert it resolves); start a new run
    through `＋ new run` (chip tap, title via fill — the
    on-screen-keyboard path — tap `submit run`, assert the run
    appears). Plus: each overlay of §Overlays opened by touch, asserted
    within the viewport (`boundingBox` inside 390×844, no horizontal
    page scroll — `document.documentElement.scrollWidth <=
    window.innerWidth`), and dismissed by touch.
15. **axe** (`a11y.spec.ts`): add the mobile state — the
    loaded-dashboard scenario at 390×844 — asserting `blocking` empty
    and score ≥ floor. With T081's `xlarge` run, the gate now covers
    desktop, mobile, and non-default type.
16. **Docs**: 10 §Layout gains the breakpoint paragraph pointing at 21
    §Narrow layout; 10 §Overlays gains the narrow sizing rule;
    §Accessibility and quality gains the mobile axe state.

## What this task is not

- **Not a redesign of the desktop.** No component's ≥ `md` markup or
  classes change beyond what wrapping requires; the splitter, rail and
  collapse behaviour above the breakpoint are untouched. One desktop
  assertion stays green: the existing suite's splitter drag.
- No second breakpoint, no orientation handling, no gesture support
  (no swipe-to-close), no new overlay, no change to overlay *content*
  or behaviour at ≥ `md` beyond the width caps.
- Not the type ramp or the chooser — that is T081, already landed;
  this task only keeps its header button visible and its `xlarge` axe
  run green.
- No plugin-contract change: plugin `custom` panels simply live inside
  the responsive detail; their internals are the plugin's problem.
- No change under `athanore/`; snapshot untouched.

## Tests

- **Vitest**: the narrow row renders both lines and the `⚠` from a
  `RunSummary`; the back control writes `run: undefined` to search; the
  shell mounts list vs detail from `?run=` when narrow (drive
  `matchMedia` with the standard mock); a unit where e2e would over-pay
  (e.g. the library's stacked layout markup below `md`).
- **Playwright**: `web/e2e/mobile.spec.ts` per steps 14–15 — the five
  touch flows, the overlay containment sweep, the mobile axe state.

## Verification

```sh
./scripts/test.sh
git diff --exit-code tests/snapshots
pnpm -C web exec playwright test mobile.spec.ts a11y.spec.ts --workers=1
```

Then by hand in devtools device mode at 390×844, touch emulation on:
run the five flows and open every overlay, watching for anything the
suite cannot see (focus lost behind a sheet, a scroll trap); drag the
window across 768 px and back — the narrow shell at 767, the exact
desktop at 768.

## Done

- At 390 px: every 21 §Touch operation flow passes by touch alone in
  CI; every overlay fits the viewport and closes by touch; no
  horizontal page scroll anywhere.
- At ≥ 768 px: pixel-identical to before the task.
- The axe gate holds at desktop, at 390×844, and at `xlarge`.
- Gate green; snapshot byte-identical.
- `**Status.** Done.` on `### T082`, in the same commit.

## Files

```
web/src/App.tsx
web/src/components/Splitter.tsx
web/src/components/Header.tsx
web/src/components/Footer.tsx
web/src/components/RunList/RunList.tsx
web/src/components/RunList/RunFilters.tsx
web/src/panes/PaneBar.tsx
web/src/lib/                          (useIsNarrow, wherever lib puts hooks)
web/src/overlays/OverlayPanel.tsx
web/src/overlays/Palette.tsx
web/src/overlays/NewRun.tsx
web/src/overlays/EditRun.tsx
web/src/overlays/Library.tsx
web/src/overlays/TaskDrawer.tsx
web/src/overlays/Pickers.tsx
web/src/overlays/Keys.tsx
web/src/overlays/DeleteRun.tsx
web/src/overlays/PluginAction.tsx
web/e2e/mobile.spec.ts                (new)
web/e2e/a11y.spec.ts
docs/v1/10-frontend.md
docs/v1/17-serial-task-plan.md        (Status line)
```

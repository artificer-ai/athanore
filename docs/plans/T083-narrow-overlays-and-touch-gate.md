# T083 — Narrow overlays and the touch gate

**Task.** `docs/v1/17-serial-task-plan.md` § `### T083`.
**Specs.** `docs/v1/21-design-refresh.md` §Narrow layout (the overlay
rules), §Touch operation and §Gates (normative — the five flows and the
three axe states); `docs/v1/10-frontend.md` §Overlays, §Accessibility
and quality; D197 (viewport and `tap()`), D178 (the axe floor).

## What this task is

The overlays' narrow form, and the gates that prove the whole phase:
after this task the requirement "usable end to end on a phone by touch
alone" is either demonstrated by CI or red.

### Overlays (below `md`)

1. **Shared surface** (`overlays/OverlayPanel.tsx` and the dialogs that
   roll their own root — D176 (3) names them): cap panel width to the
   viewport minus the backdrop margin and height to `100dvh` minus the
   same; content scrolls inside the panel, never the page.
2. **Palette** (`Palette.tsx`): full-width under the header; rows are
   ≥ 24 px touch targets.
3. **New run / edit** (`NewRun.tsx`, `EditRun.tsx`): span the width;
   the workflow chip group wraps; with the form empty, `submit run` and
   `cancel` are visible without scrolling.
4. **Library** (`Library.tsx`): full-screen sheet, columns stacked —
   list above, source viewer below.
5. **Task drawer** (`TaskDrawer.tsx`): full-screen sheet.
6. **Pickers, keys, delete, action** (`Pickers.tsx`, `Keys.tsx`,
   `DeleteRun.tsx`, `PluginAction.tsx`): sized to fit; the keys overlay
   keeps its desktop content but scrolls and closes by touch.
7. **Touch close**: every overlay closes on backdrop tap (Radix default
   — verify none of the dialogs suppress it) and any overlay header's
   close affordance is a real button.
8. **Docs**: 10 §Overlays gains the narrow sizing rule; §Accessibility
   and quality gains the mobile and font-size axe states.

### The gates

9. **`web/e2e/mobile.spec.ts`** (extending T082's file), 390×844,
   `hasTouch`, `isMobile`, every activation `tap()`, on the `probe`
   fixture workflow: the five flows of 21 §Touch operation end to end —
   view the list; open the run; cycle panes with the pane bar's `▶`
   (assert the pane label advances and wraps); answer the open
   permission request by tapping its option button (assert it resolves);
   start a new run through `＋ new run` (chip tap, title via fill —
   the on-screen-keyboard path — tap `submit run`, assert the run
   appears). Plus: each overlay of §Overlays opened by touch, asserted
   within the viewport (`boundingBox` inside 390×844, no horizontal page
   scroll), and dismissed by touch.
10. **axe** (`a11y.spec.ts`): add the mobile state — the
    loaded-dashboard scenario at 390×844 — asserting `blocking` empty
    and score ≥ floor. With T081's `xlarge` run, the gate now covers
    desktop, mobile, and non-default type.

## What this task is not

- The shell is T082's and is done: do not rework the header, footer,
  run list or pane bar here beyond what an overlay needs.
- No gesture support (no swipe-to-close), no new overlay, no change to
  overlay *content* or behaviour at ≥ `md` beyond the width caps.
- No plugin-contract change: plugin `custom` panels simply live inside
  the responsive detail; their internals are the plugin's problem.
- No change under `athanore/`; snapshot untouched.

## Tests

The Playwright additions of steps 9–10 are the tests; add vitest only
where a unit can express something e2e would over-pay for (e.g. the
library's stacked layout markup below `md`).

## Verification

```sh
./scripts/test.sh
git diff --exit-code tests/snapshots
pnpm -C web exec playwright test mobile.spec.ts a11y.spec.ts --workers=1
```

Then by hand in devtools device mode at 390×844, touch emulation on:
run the five flows and open every overlay, watching for anything the
suite cannot see (focus lost behind a sheet, a scroll trap).

## Done

- Every 21 §Touch operation flow passes by touch alone at 390×844 in
  CI; every overlay fits and closes by touch.
- The axe gate holds at desktop, at 390×844, and at `xlarge`.
- Gate green; snapshot byte-identical.
- `**Status.** Done.` on `### T083`, in the same commit.

## Files

```
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
web/e2e/mobile.spec.ts
web/e2e/a11y.spec.ts
docs/v1/10-frontend.md
docs/v1/17-serial-task-plan.md        (Status line)
```

# T081 — Base-relative type ramp and the font-size chooser

**Task.** `docs/v1/17-serial-task-plan.md` § `### T081`.
**Specs.** `docs/v1/21-design-refresh.md` §Type scale (normative — the
two tables are the values); `docs/v1/10-frontend.md` §Design system
§Type and density (the section this updates); D150 (what the utilities
are and why), D195 (rem ramp, density does not scale), D196 (where the
control lives), D178 (the axe floor).

## What this task is

Two halves of one feature: the generated theme learns to scale, and the
operator gets the control.

### The generator (`web/scripts/gen-theme.mjs`)

1. The six type utilities emit base-relative sizes, exactly 21 §Type
   scale's table: `text-metric` `calc(15rem / 12)` (weight 500 stays),
   `text-body` `1rem`, `text-row` `calc(11.5rem / 12)`, `text-meta`
   `calc(11rem / 12)`, `text-kicker` `calc(10.5rem / 12)` (uppercase and
   tracking stay), `text-hint` `calc(10rem / 12)`. Use the exact
   `calc(<px>rem / 12)` form — no rounded decimals.
2. The app type base block gains the steps, multiplying the token so a
   re-imported base flows through (21's second table):

   ```css
   html { font-size: var(--ath-font-size); line-height: 1.5; }
   html[data-font-size='small']  { font-size: calc(var(--ath-font-size) * 11 / 12); }
   html[data-font-size='large']  { font-size: calc(var(--ath-font-size) * 13.5 / 12); }
   html[data-font-size='xlarge'] { font-size: calc(var(--ath-font-size) * 15 / 12); }
   ```

   `default` is the absence of the attribute. Regenerate; commit the
   generated files; never hand-edit them.

### The SPA

3. `web/src/store/prefs.ts`: `fontSize: 'small' | 'default' | 'large' |
   'xlarge'`, default `'default'`, with a setter, added to `partialize`
   (update its "five values" comment).
4. Application: a module-level subscription (beside the store, or in
   `main.tsx` before render) that writes
   `document.documentElement.dataset.fontSize` — deleting the attribute
   for `'default'` — on load and on every change. zustand's `persist`
   hydrates synchronously from `localStorage`, so running this before
   `createRoot(...).render()` applies the choice before first paint.
5. The control: an icon-only button in `Header.tsx` beside `workflows`
   (Phosphor `TextAa`, `aria-label="text size"`, the neutral-outline
   button treatment), opening a Radix Popover containing a Radix
   RadioGroup of the four steps with the current one checked. Match the
   header's existing idiom; hit area ≥ 24×24 px.
6. The palette: four rows (`font size: small` … in
   `overlays/actions.ts`' catalogue, keyless), each setting the pref.

### The docs

7. 10 §Type and density: the ramp is base-relative, the base is the
   chooser's, pointer to 21 §Type scale. 10 §Layout's header line gains
   the text-size control.

## What this task is not

- **No density scaling.** Spacing, paddings, the 30 px rail, pixel gaps
  all stay absolute (D195). Do not convert component px to rem.
- **No settings overlay** (D196), no server pref, no URL state, no new
  localStorage key — `athanore.prefs` is the store.
- Not the narrow layout: no breakpoint, no media query in components.
  T082 is next; do not anticipate it in the header markup beyond adding
  one button.
- No change to `nocturne.css` (T080's file) or under `athanore/`.

## Tests

- **Vitest**, generated theme (extend `web/src/styles/theme.test.ts` or
  a sibling): the sheet contains the six `calc(<px>rem / 12)` sizes and
  the three `data-font-size` steps; `--check` still passes.
- **Vitest**, prefs: default `'default'`; setter persists through
  `partialize`; the subscription sets and removes the attribute.
- **Vitest**, UI: the header button opens the popover, checking a step
  dispatches; the palette rows exist and dispatch.
- **Playwright** (extend an existing spec or add `fontsize.spec.ts`):
  select `xlarge` via the header by mouse, assert `html[data-font-size]`
  and that a metric tile and a table row both grew; reload, the choice
  holds; clear storage, the default returns.
- **Playwright a11y**: an added axe run on the loaded dashboard with
  `xlarge` selected — `blocking` empty, score ≥ floor.

## Verification

```sh
./scripts/dev.sh "pnpm -C web gen:theme && git diff --exit-code web/src/styles"
./scripts/test.sh
git diff --exit-code tests/snapshots
```

Open the app, cycle the four steps: the whole interface rescales
together (metric values, rows, kickers, hints), nothing mixed-scale; at
`default` it is pixel-identical to before the task.

## Done

- The chooser is reachable from the header and the palette, rescales the
  whole ramp coherently, survives reload, and clearing site data
  restores the default.
- Gate green; snapshot byte-identical.
- `**Status.** Done.` on `### T081`, in the same commit.

## Files

```
web/scripts/gen-theme.mjs
web/src/styles/theme.css             (generated)
web/src/styles/tokens.gen.ts         (generated, if the parse changes)
web/src/store/prefs.ts
web/src/main.tsx                     (apply before first paint)
web/src/components/Header.tsx
web/src/overlays/actions.ts
web/e2e/                             (xlarge flow + axe run)
docs/v1/10-frontend.md
docs/v1/17-serial-task-plan.md       (Status line)
```

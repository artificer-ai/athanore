# T082 — The narrow shell

**Task.** `docs/v1/17-serial-task-plan.md` § `### T082`.
**Specs.** `docs/v1/21-design-refresh.md` §Narrow layout (normative —
the breakpoint, the regions, the four narrow treatments);
`docs/v1/10-frontend.md` §Layout (the desktop layout that must not
change); D194 (the stacked split), D197 (the pinned viewport).

## What this task is

The one breakpoint and the shell's narrow form: below Tailwind's `md`
(768 px) the SPA shows one middle region at a time and every region gets
its narrow treatment. At `md` and above **nothing changes** — diffing a
desktop screenshot before/after this task should show pixels identical.

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
7. **Docs.** 10 §Layout gains the breakpoint paragraph pointing at 21
   §Narrow layout.

## What this task is not

- **Not the overlays.** Dialog/sheet sizing, the stacked library, the
  mobile e2e for the five flows and the mobile axe run are T083. This
  task's e2e is the shell only.
- **Not a redesign of the desktop.** No component's ≥ `md` markup or
  classes change beyond what wrapping requires; the splitter, rail and
  collapse behaviour above the breakpoint are untouched.
- No second breakpoint, no orientation handling, no gesture.
- No change under `athanore/`; snapshot untouched.

## Tests

- **Vitest**: the narrow row renders both lines and the `⚠` from a
  `RunSummary`; the back control writes `run: undefined` to search; the
  shell mounts list vs detail from `?run=` when narrow (drive
  `matchMedia` with the standard mock).
- **Playwright** `web/e2e/mobile.spec.ts` (started here, finished in
  T083) with `test.use({ viewport: { width: 390, height: 844 },
  hasTouch: true, isMobile: true })`, every activation `tap()`:
  submit a run via the fixture, see it in the list, tap it, the detail
  fills the width, tap back, the list returns; assert no horizontal page
  scroll on both screens
  (`document.documentElement.scrollWidth <= window.innerWidth`).
- **Playwright**: one desktop spec assertion that the splitter still
  drags (the existing suite covers this; just keep it green).

## Verification

```sh
./scripts/test.sh
git diff --exit-code tests/snapshots
```

Then by eye in devtools at 390 px and at 768 px: the narrow shell at
389, the exact desktop at 768; drag across the boundary and back.

## Done

- At 390 px: list ↔ detail by touch, both regions full-width, no
  horizontal page scroll, header and footer usable by touch.
- At ≥ 768 px: pixel-identical to before the task.
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
web/e2e/mobile.spec.ts                (new)
docs/v1/10-frontend.md
docs/v1/17-serial-task-plan.md        (Status line)
```

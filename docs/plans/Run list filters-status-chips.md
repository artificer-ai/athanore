# Run list filters — status chips, a default that hides the finished, a wider `/`

**Task.** Not a `Txxx` row: operator-requested work arriving through the
`feature` workflow, after the v1 build order. Nothing in
`docs/v1/17-serial-task-plan.md` changes and no `**Status.** Done.` line
is added — this file is the scope fence instead.

**Specs.** `docs/v1/10-frontend.md` §Layout (the header strip: the
workflow chips, the `/` input, the run count; the narrow strip that
scrolls within itself; the 390 px measurement of D201), §Stack (`useUi`
is the unpersisted store, and the filter lives there), §Keyboard (`tab`
is the browser's and reaches the chips and the `/` input; a filter that
hides the row puts a held run down), §Components (chips are a `Toggle`
group, outlined, accent-tinted when on; the status pill), §Accessibility
and quality (colour is never the only signal; the axe floor), §Realtime
and caching (one cached copy of `GET /api/runs`);
`docs/v1/21-design-refresh.md` §Narrow layout (one breakpoint; no page
scroll at 390 px; strips that manage their own overflow may scroll
within themselves) and §Regions, narrow (the header's strip; 24×24 px
hit areas, WCAG 2.5.8); `docs/v1/08-api.md` §Runs (`GET /api/runs`
returns the list whole; `?status`/`?workflow` exist and stay unused);
`docs/v1/03-domain-model.md` (the six run statuses); D37 (no light
theme), D179 (Radix primitives mounted directly; selection is `?run=`),
D194 (the breakpoint), D201 (1) (the filter strip is the header's third
line at 390 px), D204 (2) (a filter that hides the selected row puts a
held run down and leaves the selection alone), D253 (3) (what `useUi`
is for).

## What this change is

The header's filter strip gains a second chip group, **one chip per run
status** — `queued`, `running`, `paused`, `completed`, `failed`,
`cancelled` — that is multi-select: a run is shown when its status is
one of the chips that are on. **The default, on every load, is the four
unfinished statuses on and `completed` and `cancelled` off**, so a fresh
page lists the work that is still going rather than months of what is
done, and an `all` chip beside the group turns every status on in one
tap. The `/` input widens from title-or-id to **id prefix, title or
workflow name**, case-insensitive. The three narrowings compose: AND
across kinds, OR within the status kind. The header's `n runs` keeps
counting every run the server returned — it is the server's number, not
the filter's, and stays so.

Nothing on the wire changes. The list is still `GET /api/runs` whole,
cached once, narrowed in the browser in one array pass
(`useRunList.ts`), for the reasons that file already gives. The filter
stays in `useUi` — transient, not persisted, not in the URL — which is
exactly what makes "the default applies on every load" true without a
line of code for it.

### What the request left open, settled here (for D268)

1. **Where the `all` chip lives and what it does.** It is a chip of the
   same look, placed first in the status group, drawn *on* only while
   every status is on. Pressing it turns every status on; pressing it
   while it is on changes nothing. It is not a member of the Radix group
   (a "select all" is not a value), so it is a `Toggle.Root` of its own
   beside a `ToggleGroup.Root type="multiple"`, and it does not toggle
   *off* — a chip that turned everything off would leave an empty list
   one tap from a full one, and a chip that "reset to default" would be
   a second meaning for the same word. Its accessible name is
   `all statuses`, so it is told apart from the workflow group's `all`
   (which stays a radio named `all`, as every test and spec has it).
2. **Every status may be switched off.** Multi-select has no "at least
   one" rule the way the workflow radio group has `all` as its floor:
   with none on the list reads `0 shown` and `all` is one tap away.
   Refusing the last toggle would be a chip that ignores a click.
3. **The id match is a prefix, not a substring.** The RUN column shows
   the first eight characters of a ULID (`SHORT_ID_LENGTH`), so a
   prefix is what an operator can read off the screen and type; a
   substring found in the middle of a ULID matched nothing anyone
   typed on purpose. The existing `contains` test uses a prefix and
   keeps passing.
4. **The chip order is the status order of 03** — the order
   `RunStatus` is declared in — and the group sits *after* the workflow
   chips and *before* the `/` input, with the counts' `│` glyph between
   the two groups. The mock's leading element (`[all][feature_build]…`)
   is untouched; the new group is added, not interleaved.
5. **A submitted run clears the whole filter to the default**, not just
   the chip and the query as today: `NewRun`'s `settle` calls one
   `resetRunFilter()` rather than two setters, because a run queued
   under a filter that hides it "looks like one that was never queued
   at all" (its own docblock), and `queued` is on in the default.
6. **Off chips are neutral, on chips are accent** — the treatment the
   workflow chips already have, not the status colours: the chip is a
   filter control, and the pill on the row is where a status is
   coloured (10 §Status colours). One look for every chip in the strip.

## Files and what each does

### 1. `web/src/store/ui.ts` — the state

Beside `ALL_WORKFLOWS`, add:

```ts
import type { RunStatus } from '../api/gen/types.gen'

/** Every run status of 03, in the order the chips are drawn. */
export const RUN_STATUSES: readonly RunStatus[] = [
  'queued', 'running', 'paused', 'completed', 'failed', 'cancelled',
]

/** The statuses on at load: everything that is not finished (D268). */
export const DEFAULT_RUN_STATUSES: readonly RunStatus[] = [
  'queued', 'running', 'paused', 'failed',
]

export type RunFilter = {
  workflow: string
  /** The statuses a run may have and still be listed (OR within). */
  statuses: RunStatus[]
  query: string
}

/** What every load starts from, and what a submitted run resets to. */
export const DEFAULT_RUN_FILTER: RunFilter = {
  workflow: ALL_WORKFLOWS,
  statuses: [...DEFAULT_RUN_STATUSES],
  query: '',
}
```

`Ui` gains:

```ts
setRunStatuses: (statuses: readonly string[]) => void
/** A run was submitted, or the default is wanted back. */
resetRunFilter: () => void
```

`setRunStatuses` takes `readonly string[]` — Radix hands back a
`string[]` — and normalises it: `RUN_STATUSES.filter((s) =>
statuses.includes(s))`, so the stored array is always in chip order and
never holds a value that is not a status, and no cast is needed at the
call site. `resetRunFilter` sets `runFilter` to a fresh copy of
`DEFAULT_RUN_FILTER` (spread it; the array too). The initial state is
the same fresh copy.

`failed` is on by default deliberately: a failed run is unfinished
business, the thing an operator retries or reruns (04), and hiding it
would hide the one status that most needs a look.

Extend the `RunFilter` docblock: what `statuses` means, what `query`
now matches (id prefix, title, workflow name), and the default.

### 2. `web/src/components/RunList/useRunList.ts` — the narrowing

- `matchesQuery(run, query)`: trim, lowercase; blank is a match; else
  `run.id.toLowerCase().startsWith(needle) ||
  run.title.toLowerCase().includes(needle) ||
  run.workflow.toLowerCase().includes(needle)`.
- New exported `matchesFilter(run: RunSummary, filter: RunFilter):
  boolean` — the three conjuncts in one place:
  `(filter.workflow === ALL_WORKFLOWS || run.workflow === filter.workflow)
  && filter.statuses.includes(run.status) && matchesQuery(run,
  filter.query)`. `useRunListModel` calls it in its `.filter(...)`.
- `total` and `active` are untouched: they read `data`, never `rows`.
- Docblock: say the strip is now three controls, and that the model
  narrows by workflow, by status and by query, AND across, OR within.

### 3. `web/src/components/RunList/RunFilters.tsx` — the chips

Import `Toggle` beside `ToggleGroup` from `radix-ui`, and
`RUN_STATUSES` (beside the existing `ALL_WORKFLOWS`, `useUi`) from the
store. Hoist the chip's class string into a module
`const CHIP = '…'` — it is now on nine elements rather than one, and
the string is the one place the look is written.

Render order, as fragment children of the header's strip wrapper:

1. The workflow `ToggleGroup.Root type="single"` — unchanged.
2. `<span aria-hidden className="text-[var(--color-neutral-800)]">│</span>`
   — the separator the counts already use, between the two groups.
3. A `<div className="flex items-center gap-[5px] max-md:flex-none">`
   holding:
   - `<Toggle.Root pressed={allOn} onPressedChange={() =>
     setRunStatuses(RUN_STATUSES)} aria-label="all statuses"
     className={CHIP}>all</Toggle.Root>` where `allOn =
     RUN_STATUSES.every((s) => filter.statuses.includes(s))`.
   - `<ToggleGroup.Root type="multiple" value={filter.statuses}
     onValueChange={setRunStatuses} aria-label="filter by status"
     className="flex items-center gap-[5px] max-md:flex-none
     max-md:flex-nowrap">` with one `ToggleGroup.Item value={status}
     className={CHIP}` per `RUN_STATUSES` entry, reading the status
     word. In multiple mode Radix draws the root as `role="toolbar"`
     and each item as a `button` with `aria-pressed` and
     `data-state="on|off"` — so the `data-[state=on]:` utilities in
     `CHIP` tint it exactly as they tint a workflow radio, and
     `aria-pressed` is what a screen reader hears. Roving focus stays
     on (Radix's default, and what the workflow group already does):
     `tab` reaches the group, `←`/`→` move within it, `space`/`⏎`
     toggle the chip under focus.
4. The `/` input — unchanged, including its `min-w-[190px]`.

Every chip keeps `max-md:min-h-[24px] max-md:whitespace-nowrap` from
the existing class, and gains `max-md:min-w-[24px]` (the shortest word
already exceeds it; the floor is what the mobile gate measures). Nothing
about the strip wrapper in `Header.tsx` changes: it is `contents` at
`md` and one horizontally scrolling `basis-full` line below it, and
the new group joins the line.

Rewrite the module docblock: three controls, not two; what the status
group is and how it differs from the workflow one (multiple, no floor,
an `all` beside rather than inside); where the `all statuses` name
comes from.

### 4. `web/src/overlays/NewRun.tsx` — one call

`settle` reads `resetRunFilter` off the store instead of
`setRunWorkflow` + `setRunQuery`, and calls it once. Adjust the
docblock sentence ("The chip and the `/` box are cleared with it") to
say the filter goes back to its default, which lists a `queued` run.

### 5. `web/src/components/Header.tsx` — docblock only

The docblock names "the workflow chips and the `/` filter" twice; make
it "the chips and the `/` filter". No markup change.

## Documents

- **`docs/v1/10-frontend.md` §Layout.** (a) The diagram's header line
  gains the status group after the workflow chips:
  `[all][feature_build][gamedev]… │ [all][queued][running][paused][completed][failed][cancelled]`.
  (b) The **Header** bullet: "workflow filter chips (accent-tinted when
  selected); status filter chips, one per run status, multi-select,
  with an `all` chip that turns every status on; a `/` filter input
  matching a run's id prefix, title or workflow name,
  case-insensitively". (c) A new paragraph after the bullets, before
  the narrow paragraph: the filter is three controls in `useUi.runFilter`
  and composes AND across the three and OR within the statuses; **the
  default on every load is the four unfinished statuses on and
  `completed` and `cancelled` off** (D268), and because `runFilter` is
  not persisted the default is what every load gets; `n runs` in the
  header is the server's count and the list's footer `n shown` is the
  filter's; the selected run's row may be filtered away — the selection
  is `?run=` and stays, the row is hidden, and a run held by `⏎` is put
  down (§Keyboard, D204 (2)). (d) The narrow paragraph's "with the chips
  and the `/` filter as a strip" already covers both groups; the D201
  sentence does too. Leave them.
- **`docs/v1/10-frontend.md` §Components.** The "Filter / workflow
  chips" row becomes "Filter chips (workflow, status)" with the same
  component cell plus: "`ToggleGroup` in single mode for the workflow
  chips, multiple for the status chips, and a `Toggle` for the status
  group's `all`".
- **`docs/v1/21-design-refresh.md` §Regions, narrow.** "then the
  workflow chips and the `/` filter as a horizontally scrollable strip"
  → "then the workflow chips, the status chips and the `/` filter as a
  horizontally scrollable strip". One phrase; the rest stands.
- **`docs/v1/15-decisions.md`.** One new row, **D268**, dated
  2026-09-13, marked `**new**`: **the run list hides `completed` and
  `cancelled` runs by default**, and the six readings above — (1) the
  `all` chip is a `Toggle` beside the group, on only when every status
  is, one-way, named `all statuses`; (2) every status may be off;
  (3) id matches by prefix; (4) chip order and placement; (5) a
  submitted run resets the whole filter to the default; (6) chips are
  accent-tinted, not status-coloured. The reason column: runs never
  expire (15 §Open questions 5) and the list is the whole history, so
  the default has to be the work still going or the first screen is
  months of `completed`; `failed` stays on because it is the status
  that needs acting on; the default costs one tap to undo, in a chip
  that is always on screen, and it is not persisted because a filter
  that survived a reload would be a filter nobody remembered setting.
- **Not** updated: `docs/v1/17-serial-task-plan.md` § T061 and
  `docs/plans/T061-run-list.md`, which describe the strip that task
  shipped; 10 is the document that specifies the behaviour.

No wire change: `tests/snapshots/openapi.json` and `web/src/api/gen`
are untouched; `git diff --exit-code` on both is part of the gate.

## Tests

Lowest layer that can express each behaviour (13 §Pyramid): the
composition in the model, the chips in `RunFilters`, the reset in
`NewRun`, the shell's count in `App.test.tsx`, and two browser cases —
one because only a browser runs a workflow to `completed` and watches
the row go, one because only a browser has a 390 px strip to measure.

**Every test that seeds `runFilter` now has to say its `statuses`**
(the type demands it). Two idioms, and which one a file uses is a
decision about what its fixtures mean:

- `useUi.setState({ runFilter: { ...DEFAULT_RUN_FILTER } })` where the
  default is what is under test or does not matter;
- `useUi.setState({ runFilter: { ...DEFAULT_RUN_FILTER, statuses:
  [...RUN_STATUSES] } })` where the file's fixtures include a
  `completed` run that its existing assertions expect to see — that is
  the honest reading of "the test was written against every run", and
  it keeps those assertions meaning what they meant.

Concretely:

- **`web/src/store/__tests__/ui.test.ts`** — new cases: `runFilter`
  starts equal to `DEFAULT_RUN_FILTER`, with `completed` and `cancelled`
  absent and the other four present; `setRunStatuses(['cancelled',
  'queued'])` stores `['queued', 'cancelled']` (chip order) and
  `setRunStatuses(['queued', 'bogus'])` stores `['queued']`;
  `resetRunFilter()` after setting all three fields puts
  `DEFAULT_RUN_FILTER` back; the "nothing reaches localStorage" case
  still passes. Add `runFilter` to the `beforeEach` reset.
- **`web/src/components/RunList/__tests__/useRunList.test.tsx`** — the
  `beforeEach` seeds all six statuses on, so the existing eleven cases
  keep their meaning (two of the three fixtures are `completed`). Add:
  `matchesQuery` unit cases (id prefix matches, a mid-ULID substring
  does not, title substring, workflow substring, case-insensitive,
  trimmed); `matchesFilter` is what the model uses; "hides completed
  and cancelled under the default" — seed `DEFAULT_RUN_FILTER`, expect
  only `bbbb2222`, `total` still `3`; "a status chip narrows, OR
  within" — statuses `['completed']` shows `aaaa1111,cccc3333`,
  `['running','completed']` shows all three, `[]` shows none and
  `total` is still `3`; "status and workflow compose, AND across" —
  `feature_build` + `['completed']` shows `cccc3333` only; "status,
  workflow and query compose" — add `['running']` to the existing
  chip-and-query case and expect nothing, then `['completed']` and
  expect `cccc3333`; "narrows on the workflow name" — query `gamedev`
  shows `aaaa1111`.
- **`web/src/components/RunList/__tests__/RunFilters.test.tsx`** — the
  `beforeEach` seeds `DEFAULT_RUN_FILTER`. Keep the five cases (the
  workflow chips are still `radio`s). Add: "offers one status chip per
  status, in 03's order, after `all statuses`" — `getByRole('toolbar',
  { name: 'filter by status' })` holds six `button`s reading
  `RUN_STATUSES` in order, and `getByRole('button', { name: 'all
  statuses' })` precedes it; "starts with completed and cancelled off"
  — those two `aria-pressed="false"` / `data-state="off"`, the other
  four on, `all statuses` off; "`all statuses` turns every status on
  and is on only then" — click it, expect `runFilter.statuses` to equal
  `RUN_STATUSES` and the chip `aria-pressed="true"`; click it again,
  nothing changes; "a status chip toggles" — click `completed` on, then
  `running` off, and read the store after each; "every chip can be off"
  — from the default, click the four that are on, expect `[]`; "chips
  are reachable by tab and toggle with space and enter" — `userEvent.tab()`
  from the document until `document.activeElement` is inside the status
  toolbar (the roving group lands on one item; `{ArrowRight}` moves along
  it to `completed`), then `{ }` toggles it on and `{Enter}` toggles it
  off, each read off the store; "the workflow `all` and
  the status `all` are two controls" — `getByRole('radio', { name: 'all'
  })` and `getByRole('button', { name: 'all statuses' })` both resolve
  and are different elements.
- **`web/src/components/__tests__/Header.test.tsx`** — the
  `beforeEach` seeds `DEFAULT_RUN_FILTER`; the "carries the run list's
  chips" case additionally expects the status toolbar and the `all
  statuses` button to be in the document.
- **`web/src/App.test.tsx`** — `freshTab` seeds all six on (the second
  fixture is `completed`, and eight cases read two rows). Add one case:
  "hides the completed run by default and still counts it" — seed
  `DEFAULT_RUN_FILTER`, `shell()`, expect one row (`rebuild run
  detail`), `rows-shown` to read `1 shown`, `run-count` to read `2
  runs`; then click `getByRole('button', { name: 'all statuses' })`
  and expect two rows. And one more: "keeps the selection when the
  filter hides its row" — seed the default, `shell({ run:
  'cccc3333dddd' })`, expect no row for it, `onSelectRun` not called,
  and `pane-label` reading `OVERVIEW (1/3)` — the run's own cycle, as
  the existing selected-run cases read it, not the inbox's `(1/1)`
  that an empty selection shows.
- **`web/src/overlays/__tests__/NewRun.test.tsx`** — the two seeds
  become `DEFAULT_RUN_FILTER` spreads; the "clears the run list's
  filter" case seeds `{ workflow: 'gamedev', statuses: ['completed'],
  query: 'boss' }` and expects `DEFAULT_RUN_FILTER` back.
- **`web/e2e/support/fixtures.ts`** — `Dashboard.showAllStatuses(by:
  Gesture = 'click')`: act on `header` → `getByRole('button', { name:
  'all statuses' })`, then expect it to have `aria-pressed="true"`.
  Documented as: *the list hides finished runs by default (10 §Layout,
  D268); a spec that watches a run finish, or submits one that finishes
  without a request in the way, turns the chip on first, because
  `status()` reads the row.* Also `statusChip(status: string): Locator`
  → the toolbar's `button` named exactly `status`, for the specs below.
- **Existing specs, one line each, straight after `dashboard.open()`:**
  `run.spec.ts` (both tests), `fanout.spec.ts`, `inbox.spec.ts`,
  `registration.spec.ts` (both tests — `tempo` finishes as soon as the
  hold file is absent, and `submit()` waits for the row), `plugin.spec.ts`
  (both tests — `plugged` finishes at once and `select()` clicks the
  row), and `mobile.spec.ts` test 1 (`showAllStatuses('tap')`, because
  flow 4 ends on `completed`). No other spec reaches `completed` or
  `cancelled` in the list: `hold` runs stay `running`, `flop` ends
  `failed`, which the default shows, and the `⇧D` case deletes the row
  outright. Each added line carries a short comment naming why.
- **`web/e2e/filters.spec.ts`** — new, desktop, one test: "the list
  hides finished runs until asked, and counts them anyway". `open()`;
  `submitOverApi('hold', 'still going')` and `id =
  submitOverApi('plugged', 'done and gone')`; expect `row('still
  going')` visible and `row('done and gone')` to have count 0 with
  `RUN_TIMEOUT` (it may pass through `queued`/`running` first — the
  retrying matcher waits it out); `run-count` reads `2 runs`,
  `rows-shown` reads `1 shown`. `showAllStatuses()`; expect the row
  back with `status('done and gone')` reading `completed`. Click
  `statusChip('completed')` off: gone again. Then the query, with all
  on: fill the `/` input with `id.slice(0, 8).toLowerCase()` → only
  `done and gone`; with `PLUGGED` → the same; with `hold` → only
  `still going`; clear it. Then the selection rule: `select('still
  going')`, `page.keyboard.press('c')` (cancel needs no confirm, 10
  §Keyboard), expect the row to have count 0 with `RUN_TIMEOUT` while
  `?run=` still names it and `[data-region="detail"]` is still up —
  selection kept, row hidden. Finally click `statusChip('cancelled')`
  and expect `status('still going')` to read `cancelled`.
- **`web/e2e/mobile.spec.ts`** — extend "the narrow chrome" test: the
  strip also contains `completed`; `getByRole('toolbar', { name: 'filter
  by status' })` is inside `strip`; every one of the seven status chips
  (`all statuses` and the six) passes `tappable`; the strip's
  `scrollWidth` is now strictly greater than its `clientWidth` (seven
  more chips do not fit in 362 px, which is the point of the strip);
  tap `completed` and expect `aria-pressed="true"`, tap again and
  `false`; `noHorizontalScroll(page)` after each. The `probe` run this
  test submits parks at a request, so nothing here needs
  `showAllStatuses`.
- **`web/e2e/a11y.spec.ts`** — no new case: the axe sweep already
  covers the header in every state, and the toolbar is labelled. Run
  it.

## Verification

```sh
./scripts/test.sh
git diff --exit-code tests/snapshots web/src/api/gen
pnpm -C web exec playwright test filters.spec.ts mobile.spec.ts run.spec.ts plugin.spec.ts registration.spec.ts fanout.spec.ts inbox.spec.ts a11y.spec.ts --workers=1
```

Then by hand, `./scripts/run.sh` with a mix of finished and running
runs: reload and confirm only the unfinished are listed and the header
count is the full number; `all`; each chip off and on; every status
off (`0 shown`); type a short id, a title fragment and a workflow
name; select a running run, `c`, watch the row go and the detail stay;
submit a run under a narrowed filter and watch the filter reset;
`tab` from the `/` input backwards through both groups and toggle with
`space`; drag the window under 768 px and scroll the strip with a
trackpad; check the header at 1024 px, where the strip will wrap to a
second line above the breakpoint — that is `flex-wrap` doing what it
does, and is accepted.

## Done

- Six status chips and an `all` in the header strip; multi-select;
  accent-tinted when on; `completed` and `cancelled` off on every load.
- `/` matches id prefix, title and workflow name, case-insensitively.
- Workflow, status and query compose: AND across, OR within.
- `n runs` counts every run; `n shown` counts the filtered rows.
- A submitted run resets the filter to the default.
- At 390 px: the strip scrolls within itself, every chip is ≥ 24×24 px,
  the page does not scroll sideways, nothing is dropped.
- `tab` reaches both groups; `space`/`⏎` toggle; `/` still focuses the
  input.
- 10 §Layout, 10 §Components, 21 §Regions, narrow updated; D268
  recorded.
- Gate green; `tests/snapshots` and `web/src/api/gen` byte-identical.

## Out of scope (from the brief)

No server-side filtering: `?status` and `?workflow` on `GET /api/runs`
stay unused, and no query key changes. No persistence of `runFilter`
and no `?status=` search parameter. No light theme (D37). No per-workflow
status sets: the six chips are always the six. No change to what the
status pill draws, to the palette, or to the keyboard map.

## Files

```
web/src/store/ui.ts
web/src/components/RunList/useRunList.ts
web/src/components/RunList/RunFilters.tsx
web/src/overlays/NewRun.tsx
web/src/components/Header.tsx
web/src/store/__tests__/ui.test.ts
web/src/components/RunList/__tests__/useRunList.test.tsx
web/src/components/RunList/__tests__/RunFilters.test.tsx
web/src/components/__tests__/Header.test.tsx
web/src/App.test.tsx
web/src/overlays/__tests__/NewRun.test.tsx
web/e2e/support/fixtures.ts
web/e2e/filters.spec.ts
web/e2e/mobile.spec.ts
web/e2e/run.spec.ts
web/e2e/fanout.spec.ts
web/e2e/inbox.spec.ts
web/e2e/registration.spec.ts
web/e2e/plugin.spec.ts
docs/v1/10-frontend.md
docs/v1/21-design-refresh.md
docs/v1/15-decisions.md
```

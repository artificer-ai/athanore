# overview pane layout — TITLE and DESCRIPTION get the pane's width

**Task.** Not a `Txxx` row: operator-reported work arriving through the
`feature` workflow, after the v1 build order. Nothing in
`docs/v1/17-serial-task-plan.md` changes and no `**Status.** Done.` line
is added — this file is the scope fence instead.

**Specs.** `docs/v1/10-frontend.md` §Panes item 1 (the overview pane's
four sections, its field list and the "Field sources" sentence that
carries DESCRIPTION's dash rule), §Type and density (the ramp; nothing
writes a size of its own), §Accessibility and quality;
`docs/v1/09-plugins.md` §Panel kinds (the `overview` kind is `dashboard`
plus `meta`; the `kv` kind is a description list) and §Slots (the
`placement="card"` panels that append below);
`docs/v1/01-vision-and-scope.md` §Real data only (an unknown is omitted,
never zero-filled or invented); `docs/v1/21-design-refresh.md` §Type
scale (D195 — a call site writes `calc(…rem / 12)` or nothing);
D161 (the renderer supplies DESCRIPTION's `—`, and the field order is
10's), D179 (the document moves with the tree), D195, D207 (5) (the
precedent for superseding a detail of the mock in a decision row rather
than editing `docs/v1/design/Athanore.dc.html`).

The operator's sketch is
`.athanore/Screenshot 2026-09-09 at 6.21.43 PM.png`: STATS box, the meta
fields in their grid (`run`, `workflow`, `status` / `age`, `session`,
`agents`), then `title: …` and a description running the full width of
the pane over three lines, then NODES.

## What this change is

Today every meta field the `overview` builtin's route sends goes through
one door: `formatMeta` formats it and `KvPane` draws it into a
`repeat(auto-fit, minmax(240px, 1fr))` grid whose value column is
`minmax(0, 1fr)` beside an 86 px key. That is the right shape for `RUN`,
`AGE` or `SESSION` — short values, two or three to a row. It is the
wrong shape for a run description, which is written in a textarea (10
§Overlays) and can be a paragraph: in a 240 px-wide grid cell it wraps
into a narrow column that pushes the whole grid — and the sections under
it — down the pane, while the rest of the pane's width sits empty beside
it.

So TITLE and DESCRIPTION leave the grid and get a block of their own,
full width, one under the other. The meta grid keeps the six fields that
belong in a grid — RUN, WORKFLOW, STATUS, AGE, SESSION, AGENTS — and the
route, the wire contract and the OpenAPI snapshot are untouched: this is
entirely a question of where the renderer puts what the route already
sends.

**Nothing about the values changes.** `formatValue` still prints them,
DESCRIPTION is still the run's or `—` (10 §Panes, D161), and neither is
truncated, re-wrapped or re-cased. The block is a layout, not a
formatter.

### The brief's three open questions, settled

1. **A `dl`, one field per row, `dt` above `dd`.** The pairing is what it
   already is — a term and its description — and that is what a screen
   reader announces; it is the same reason `KvPane` and the OUTPUTS list
   in `Overview.tsx` are both `dl`s, and this pane should not grow a
   third idiom for the same relationship. What changes against the grid
   is only the axis: the `dt` sits *above* its `dd` instead of in an
   86 px column beside it, so the value starts at the pane's left edge
   and ends at its right.
2. **Yes, labels — `TITLE` and `DESCRIPTION`, as kickers.** 10 §Panes
   names these two fields exactly as it names the other six, and the
   operator's sketch writes `title:` and `description:` in front of the
   values. Dropping the labels would make the first line of the block a
   bare string with nothing saying what it is, which is worse for the
   empty case in particular: an unlabelled `—` says nothing at all. The
   `dt` carries `KvPane`'s own key styling (`text-hint`,
   `tracking-[0.1em]`, `text-muted-foreground`), so the block reads as
   part of the same pane rather than as a new one.
3. **Yes, the block is a `Section`.** It is a section of the overview
   like the other four, and `Section` is what gives them the mock's
   `12px 14px` over a `neutral-900` rule. It is drawn **without a
   `label`**, exactly as the meta grid is: `Section`'s `label` is a
   kicker *and* the `aria-label`, and there is no name in 10 §Panes for
   a block holding these two fields — inventing one (`ABOUT`, `RUN
   INFO`) would put a word on screen no document asked for, and the two
   `dt`s already label the two fields.

### Where it goes: under the meta grid, above NODES

The brief says "a new section after STATS"; the operator's sketch is
more specific, and it is the sketch of what they want: `title` and
`description` sit **below** the `run` / `workflow` / `status` / `age` /
`session` / `agents` fields and above `nodes`. Both readings are "below
the STATS metrics"; the sketch decides between them, and it puts the
block fourth in a five-section pane. That is also the ordering 10 §Panes
already implies — DESCRIPTION is the *last* field of the meta list, and
this block is the tail of that list unrolled to full width rather than a
new thing wedged between the tiles and the grid.

Section order after the change: `STATS` → meta grid → title and
description → `NODES` → `OUTPUTS` → `cards`.

## Files and what each does

### 1. `web/src/panes/kinds/overview.ts` — the reading rule

`formatMeta` stops emitting the two fields, and a sibling emits them.

- In `formatMeta`'s loop, skip `TITLE` and `DESCRIPTION`, and delete the
  `if (!(DESCRIPTION_KEY in out)) out[DESCRIPTION_KEY] = DASH` tail: the
  dash moves with the field. `TITLE_KEY = 'TITLE'` joins the existing
  `DESCRIPTION_KEY` constant. Every other key keeps the rule it has —
  AGE humanised, SESSION cut to `SESSION_LENGTH`, AGENTS grouped, the
  rest through `formatValue` — and key order stays the source's, so the
  grid draws RUN, WORKFLOW, STATUS, AGE, SESSION, AGENTS in the order 10
  §Panes lists them, with SESSION and AGENTS still absent until an agent
  has run.
- Rewrite `formatMeta`'s docstring: the paragraph about DESCRIPTION
  belongs to the new function now, and the docstring should say in one
  sentence *why* two fields are missing from a function called
  `formatMeta` — otherwise the next reader adds them back.

Add:

```ts
/** The two fields the grid is the wrong shape for (10 §Panes). */
export type RunAbout = {
  /** The run's title, or `null` when the source sent none. */
  title: string | null
  /** The run's description, or `—` (10 §Panes, D161). */
  description: string
}

export function formatAbout(meta: Record<string, unknown>): RunAbout | null
```

- `null` when the source sent **neither** key: an `overview`-kind panel
  a plugin declares need not be about a run at all (09 §Panel kinds), and
  a block reading `TITLE — / DESCRIPTION —` under such a panel would be
  the renderer inventing two fields nobody sent (01 §Real data only).
  The pane draws no section for `null`.
- `title` is `formatValue(meta['TITLE'])` when the key is present and
  `null` when it is absent — the row is dropped, not dashed. 10 §Panes
  gives the dash to DESCRIPTION and to nothing else, and the builtin's
  route always sends `TITLE` (`athanore/plugins/builtin/overview.py`
  `_meta`, `run.title` is non-optional on the wire), so an absent TITLE
  can only come from a plugin panel that meant not to have one.
- `description` is `formatValue(meta['DESCRIPTION'])` when present and
  `DASH` when absent — the rule that was in `formatMeta`, unchanged and
  in one place, which is what keeps "DESCRIPTION is the run's, or `—`"
  true after the move.

Both values go through `formatValue` and nothing else: no truncation, no
`preview()`, no whitespace normalisation. A description with newlines
renders the way the grid rendered it (HTML collapses the runs); making
newlines significant would be a change to *how the value is formatted*,
which the brief puts out of scope.

### 2. `web/src/panes/kinds/index.ts` — the barrel

Add `formatAbout` and `type RunAbout` to the `./overview` re-export
block, in its alphabetical order (`formatAbout` before `formatCost`,
`type RunAbout` beside `type OutputLine` / `type TokenBar`). The pane
tests import from `../kinds`, so the new function has to come out of the
barrel like its siblings.

### 3. `web/src/panes/kinds/Overview.tsx` — the block

- Import `formatAbout` (and `type RunAbout` if the sub-component is
  typed on it) alongside `formatMeta`.
- `const about = formatAbout(data.meta)` beside the existing
  `const meta = formatMeta(data.meta)`.
- Render, between the meta-grid `Section` and the NODES `Section`:

```tsx
{about !== null && (
  <Section testId="overview-about">
    <dl className="flex flex-col gap-[10px]">
      {about.title !== null && (
        <div>
          <dt className="text-hint tracking-[0.1em] text-muted-foreground">TITLE</dt>
          <dd className="text-body [overflow-wrap:anywhere] text-[var(--color-neutral-300)]">
            {about.title}
          </dd>
        </div>
      )}
      <div>
        <dt className="text-hint tracking-[0.1em] text-muted-foreground">DESCRIPTION</dt>
        <dd className="text-body [overflow-wrap:anywhere] text-[var(--color-neutral-300)]">
          {about.description}
        </dd>
      </div>
    </dl>
  </Section>
)}
```

  Written out rather than mapped, because there are two fields, they are
  not interchangeable (one may be absent, one is always drawn) and a
  `map` over a two-entry array would hide that. Both rows carry a
  `dt`/`dd` inside a `div`, which is the wrapper `KvPane` and the
  OUTPUTS list already use and is valid inside a `dl`.
- The classes are `KvPane`'s, moved: `text-hint` for the key,
  `text-body` and `[overflow-wrap:anywhere]` and `--color-neutral-300`
  for the value. **No new sizes, weights or colours** — the brief puts
  styling refinements out of scope, and D195 forbids a `text-[…px]` at a
  call site in any case. The one number written here is the `10px` row
  gap, which is `KvPane`'s own `gap-y-[10px]`.
- `testId="overview-about"`: the pane's ids are `overview-meta`,
  `overview-outputs`, `token-bars`, `node-rows`, and this follows them.
  It is a test id and not copy, so naming the block does not put a word
  on screen that no document uses.
- Update the module docstring: it opens by naming "Four sections in the
  mock's order" — it is five now, and the sentence should say the block
  is where 10 §Panes' TITLE and DESCRIPTION went and why (a description
  is a paragraph and the grid is 240 px wide).
- Nothing else in the file moves: the `Object.keys(meta).length > 0`
  guard on the meta grid stays and now correctly draws nothing at all
  for a source whose meta held only those two keys, rather than
  `KvPane`'s "nothing to show".

### 4. `docs/v1/10-frontend.md` §Panes item 1 — the document moves with the tree

Two edits, both inside item 1 (D179):

- The section list. The clause reading

  > a two-column `kv` meta grid (RUN, WORKFLOW, TITLE, STATUS · node,
  > AGE, SESSION, AGENTS, DESCRIPTION);

  loses two fields — leaving RUN, WORKFLOW, STATUS · node, AGE, SESSION,
  AGENTS — and gains a clause after it for the new block: a full-width
  TITLE and DESCRIPTION block under the grid, each label over its value,
  so a description that runs to a paragraph has the pane's width instead
  of a grid column.
- The "Field sources" sentence: keep its last clause — DESCRIPTION is
  the run's, or the dash — word for word, because the rule did not
  change; if it reads as though it is describing a grid field, say
  instead that it is the block's second row.

Nothing else in 10 changes. §Layout, §Keyboard, §Overlays and the
narrow-layout rules of 21 do not mention these fields.

`docs/v1/09-plugins.md` line 290 (`overview` = `dashboard` + `kv` meta +
`table`) stays true and is **not** edited: the panel kind is unchanged,
only where the builtin pane draws two of the meta keys.

`docs/v1/design/Athanore.dc.html` is **not** edited. Its `meta` array
still lists TITLE and DESCRIPTION among the eight; the mock is the design
reference and is superseded in the decision row, as D207 (5) superseded
its `d` chip, rather than being rewritten under the tree.

`athanore/plugins/builtin/overview.py` is **not** edited. `_meta` still
sends both keys, and its docstring's claim — "the renderer supplies the
dash for the key this omits" — is still exactly what happens.

### 5. `docs/v1/15-decisions.md` — D208

One row, `**new (2026-09-10)**`, in the table's format, covering:
(1) TITLE and DESCRIPTION leave the `kv` grid for a full-width `dl` block
of their own, fourth of five sections, under the grid and above NODES,
on the operator's sketch; (2) the block is a `Section` with no label,
and its two `dt`s are the labels, because 10 §Panes has no name for the
pair and inventing one would be copy no document asked for; (3)
`formatAbout` owns DESCRIPTION's `—` now, and returns `null` when the
source sent neither key, so a plugin's `overview` panel does not grow two
invented fields; an absent TITLE drops its row rather than dashing it,
because 10 gives the dash to DESCRIPTION alone; (4) the mock's eight-item
`meta` array is superseded here; (5) no wire change — the route sends the
same eight keys and `tests/snapshots/openapi.json` is untouched.
Reason column: a run description is written in a textarea and can be a
paragraph, and the grid it was drawn in is `minmax(240px, 1fr)` — so the
one field most likely to be long was the one field guaranteed to be
narrow, and it pushed NODES down the pane while most of the pane's width
sat empty beside it.

## Tests

All in `web/src/panes/__tests__/Overview.test.tsx`, at the lowest layer
that can express it (13 §Pyramid): this is DOM structure, so jsdom is
the layer. No Playwright test is added — no spec under `web/e2e/` selects
a meta field or the overview's sections, and the a11y sweep's second
state (a dashboard with a run selected) walks the new markup already, so
a `dl` that was malformed or a `dt` with no `dd` would be caught there
without a new spec.

Edit the existing `the kv meta grid` describe block:

- `draws 10 §Panes’ fields…`: drop the TITLE and DESCRIPTION assertions;
  keep RUN, WORKFLOW, STATUS, AGE, SESSION, AGENTS; add that
  `within(screen.getByTestId('overview-meta')).queryByText('TITLE')` and
  `…queryByText('DESCRIPTION')` are both `null` — the point of the
  change is that they are *not* there.
- `keeps DESCRIPTION as a dash for a run that has none`: move it into the
  new block's suite (below).
- The field-order assertion in that test becomes the grid's six, and for
  `IDLE_OVERVIEW_SOURCE` — which sends no SESSION, AGENTS or DESCRIPTION
  — `['RUN', 'WORKFLOW', 'STATUS', 'AGE']`.

Add a describe block, `the title and description block`:

- **draws both, labelled, from `OVERVIEW_SOURCE`**: inside
  `overview-about`, `getByText('TITLE').nextSibling` has the fixture's
  title and `getByText('DESCRIPTION').nextSibling` its description, whole
  — assert the description's full text, so a later truncation of a field
  the brief froze fails here.
- **it is a `dl`, and its rows are not the grid's**: the `overview-about`
  section contains a `dl` that is not the `pane-kv` element
  (`queryByTestId('pane-kv')` within it is `null`), and each `dd` is the
  next sibling of its `dt` — the pairing question 1 settled.
- **it sits under the meta grid and above NODES**: read the sections in
  document order (`container.querySelectorAll('section')`) and assert the
  sequence of their `data-testid` / `aria-label` is STATS, `overview-meta`,
  `overview-about`, NODES. This is the placement decision above, pinned.
- **DESCRIPTION is a dash for a run that has none** (the moved test):
  `IDLE_OVERVIEW_SOURCE` draws the block with its title and a `—`, and
  `overview-meta` has no DESCRIPTION key at all.
- **no TITLE row when the source sent no title**:
  `draw({ ...OVERVIEW_SOURCE, meta: { RUN: OVERVIEW_RUN, DESCRIPTION: 'only a description' } })`
  draws `overview-about` with DESCRIPTION and no `TITLE` label — an
  absent field is absent, not dashed.
- **no block at all when the source sent neither**:
  `draw({ ...OVERVIEW_SOURCE, meta: { RUN: OVERVIEW_RUN, WORKFLOW: 'w' } })`
  leaves `queryByTestId('overview-about')` `null`, and the meta grid
  still draws its two fields.
- **a long description is not cut**: a meta whose DESCRIPTION is a string
  well past `PREVIEW_LENGTH` renders in full — the pane has no truncation
  and must not grow one on the way to being wide.

Add unit coverage for `formatAbout` next to the existing `formatCount` /
`formatSeconds` cases: `null` for `{}`, the dash for a meta with TITLE
and no DESCRIPTION, `title: null` for a meta with DESCRIPTION and no
TITLE, and both formatted for the full one.

`web/src/panes/__tests__/fixtures.ts` is **not** changed:
`OVERVIEW_SOURCE` and `IDLE_OVERVIEW_SOURCE` are the route's answers and
the route did not change. The two cases above that need a different meta
build it inline, which is what `draw`'s `unknown` parameter is for.

## Verification

```sh
./scripts/dev.sh "pnpm -C web typecheck"
./scripts/dev.sh "pnpm -C web lint"
./scripts/dev.sh "pnpm -C web test"
./scripts/dev.sh "pnpm -C web build"
./scripts/test.sh                      # the gate, including web/e2e
```

`ramp.test.ts` must stay green — no `text-[…px]` and no inline
`fontSize` in the new markup — and `git diff --exit-code tests/snapshots
web/src/api/gen` must be empty: nothing here touches the wire, so
`scripts/dump_openapi.py` and `pnpm -C web gen` are not run.

Worth looking at once in a browser (`./scripts/run.sh`, a run with a
long description, e.g. edited through `e` on any run): the description
should reach both edges of the pane's `14px` padding, and the pane
should read STATS, grid, title/description, NODES top to bottom at both
a wide pane and a narrow one (`b` to hide the run list, and the splitter
dragged in), since the block is the one part of the pane with no grid
under it to hold a minimum width.

## Done

- `formatMeta` returns RUN, WORKFLOW, STATUS, AGE, SESSION, AGENTS and
  never TITLE or DESCRIPTION; `formatAbout` returns those two, with
  DESCRIPTION's `—` and with `null` for a meta that has neither.
- `Overview.tsx` draws a fifth `Section`, unlabelled, between the meta
  grid and NODES, holding a full-width `dl` of TITLE over its value and
  DESCRIPTION over its value.
- 10 §Panes item 1 lists six fields in the grid and names the block;
  D208 is in `15-decisions.md`.
- The gate is green, and `tests/snapshots/openapi.json` and
  `web/src/api/gen` are unchanged.

## Out of scope (from the brief)

- The overview route's response shape or the keys it sends
  (`athanore/plugins/builtin/overview.py` is not edited).
- How TITLE or DESCRIPTION are formatted or truncated — `formatValue`
  and nothing else, no `preview()`, no newline handling, no clamp.
- Styling past the layout: no new font sizes, weights or colours; the
  block borrows `KvPane`'s classes exactly.
- Behaviour: nothing in the block is clickable, focusable or expandable.
- Other panes, and the six meta fields that remain — their order,
  formatting and responsiveness are untouched.

## Files

- `web/src/panes/kinds/overview.ts`
- `web/src/panes/kinds/Overview.tsx`
- `web/src/panes/kinds/index.ts`
- `web/src/panes/__tests__/Overview.test.tsx`
- `docs/v1/10-frontend.md`
- `docs/v1/15-decisions.md`

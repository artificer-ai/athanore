# delete not working — draw the shift the delete key needs

**Task.** Not a `Txxx` row: operator-reported work arriving through the
`feature` workflow, after the v1 build order. Nothing in
`docs/v1/17-serial-task-plan.md` changes and no `**Status.** Done.` line
is added — this file is the scope fence instead.

**Specs.** `docs/v1/10-frontend.md` §Keyboard (the map, exhaustive; the
sentence that moved delete from `d` to `D`; the two rules stated about
the map rather than in it), §Layout (the footer strip's chips),
§Overlays (the `?` overlay is "the footer chips, expanded"; the palette
and the delete confirm), §Accessibility and quality (colour, and text,
are never the only signal); `docs/v1/04-orchestrator.md` §Operator
operations (`delete` cancels the run and deletes every child row);
`docs/v1/08-api.md` §Runs (`DELETE /api/runs/{id}`); D51 (delete moved
off `d` so a `d` meant for "deny" one focus ring away cannot reach the
confirm), D175 (5) and D170 (the palette lists what the app can do; a
row with no key prints `—`), D176 (4) (the map dispatches on the
palette's key column), D206 (the graph pane's canvas, because it is the
newest thing that could have swallowed a keystroke and did not).

## What this change is

**The reported failure is not in the code path — it is in what the app
tells the operator to press.** The footer strip, which is the one
always-visible advertisement of the map, draws a chip reading `D` beside
the label `delete run`, in an interface whose every other word is
lowercase. The operator reads that chip and presses `d`. `d` is the
request panel's *deny* and, outside a request panel, deliberately
reaches nothing at all (D51) — so nothing happens, silently, and the
delete key "is not working".

The change is to draw the keystroke rather than the letter: every place
the map is drawn — the footer strip, the `?` overlay and the palette's
key column — draws the delete cap as `⇧D`. Nothing about what is *bound*
changes: the handler still dispatches on `event.key`, `KEY_BINDINGS`
still transcribes 10 §Keyboard's `D`, and `d` still belongs to the
request panel and to nothing else.

The second half is coverage. The keystroke had no browser-level test at
all: `web/e2e/keyboard.spec.ts` drives `n`, `?`, `b`, `^p` and `a`, and
`D` appears in the suite only as a key that is *suppressed*. Nothing in
the tree could answer "does Shift+D delete a run in a browser" without
someone writing a throwaway spec, which is how this task's diagnosis had
to be done. One e2e test closes that.

### The brief's three open questions, settled

They were settled empirically, in the browser the gate uses — a
throwaway spec under `web/e2e/`, chromium, one `athanore serve` per test
with `FakeACPAgent` behind every agent, driven through the `Dashboard`
page object. It has been deleted; what it found:

1. **Yes — the operator is pressing lowercase `d`.** That is the only
   reading of "delete with the `d` key is not working" that the code
   supports, and the app invites it: the chip says `D` and drops the
   row's own `note` (`'shift, and it asks first'`), which only the `?`
   overlay draws. `d` outside a request panel is inert by design and
   must stay inert (D51).
2. **Nothing happens, and no other action fires.** `handleKey` checks
   `event.key === 'd'` before the app's own keys, finds no registered
   request panel containing the target, and returns `false` without
   preventing the keystroke. No fallthrough, no wrong action, no error.
3. **The bug is in neither the keybinding recognition nor the overlay
   dispatch nor the delete flow — all three work.** With a run selected,
   `Shift+D` navigates to `?overlay=delete` and the confirm appears; the
   confirm's `delete run` button issues `DELETE /api/runs/{id}`, the row
   goes, and `?run=` is cleared. Verified from the page itself, from a
   focused run row, from inside a request panel, from the React Flow
   canvas with focus in the pane, while a run is held by `⏎`, and
   immediately after each of the palette, `?`, new-run, edit-run,
   pick-retry and library overlays had been opened and closed — no
   leaked keyboard claim, and React Flow's `selectionKeyCode: 'Shift'`
   watcher does not `preventDefault` the `D` keydown (its
   `isMatchingKey` compares set sizes, so `{Shift, D}` does not match
   `['Shift']`). The existing jsdom tests
   (`web/src/App.test.tsx` § the keyboard map,
   `web/src/keys/__tests__/useKeymap.test.tsx`) assert the same thing
   and pass.

So there is no defect to fix in `useKeymap.ts`, `actions.ts`,
`DeleteRun.tsx` or the API, and this plan changes none of them.

### The rule, so the list stays derived

A cap in this map stands for the character the operator types: `?` is
`?`, `⏎` is `⏎`, `^p` is the app's own chord notation for ctrl. `D` is
the one cap whose *only* difference from another cap in the same table
is its case — which is exactly why D51 chose it — and a case is not
something a chip can show in an all-lowercase interface.

So the label is derived, not listed: **a cap that is one uppercase
letter is drawn with a shift chip**, because a single capital cannot be
typed any other way. Today that is `D` and nothing else; `^p`, `^r`,
`?`, `⏎`, `esc`, `tab`, `1–9` and the arrows are untouched, and a
capital added to the map later is drawn correctly with no edit.

`⇧` (U+21E7) is the glyph. The strip already draws `↑` (U+2191) and
`⏎` (U+23CE) from the same font stack, and `⏎` is the rarer of the two,
so the coverage bar this asks for is one the app already clears.
`shift+D` was the alternative and does not fit: the palette's key column
is a 40 px grid track, sized for `^r`.

## Files and what each does

### 1. `web/src/lib/keys.ts` — the one table, plus how a cap is drawn

Add, below `KeyBinding` and above `KEY_BINDINGS`:

```ts
/** The shift chip: U+21E7, the strip's own arrow family. */
export const SHIFT_CAP = '⇧'

/**
 * A cap as the operator has to type it.
 *
 * The table's caps are 10 §Keyboard's and the handler dispatches on
 * them directly (`keys/useKeymap.ts` `capOf` returns `event.key`), so
 * `D` is what runs the delete confirm. `D` is also the one cap of this
 * map whose only difference from another cap in it is its case — which
 * is why D51 chose it — and a chip reading `D` in an interface whose
 * every other word is lowercase reads as the letter `d`, which is the
 * request panel's deny and reaches nothing else. So a cap that is one
 * uppercase letter is *drawn* with the shift chip and still *bound*
 * without it: the modifier is drawn, not bound (D207).
 */
export function capLabel(cap: string): string {
  return /^[A-Z]$/.test(cap) ? `${SHIFT_CAP}${cap}` : cap
}
```

Leave everything else alone. In particular:

- **`KEY_BINDINGS` is unchanged.** It is 10 §Keyboard transcribed, and
  `lib/__tests__/keys.test.ts` asserts both directions of that against a
  quotation of the section; the `delete-run` row keeps `keys: ['D']`.
- **The `delete-run` row's `note` is unchanged** (`'shift, and it asks
  first'`). The `?` overlay states the rule in words beside the chip,
  which is what an expanded panel is for, and 10 §Keyboard's own
  parenthetical is "(shift)".
- **`KEY_NOTES` gains nothing.** Those are the rules 10 states *about*
  the map's behaviour; how a cap is drawn is not one of them.

Extend the module docblock's paragraph about the rows with one sentence:
the rows are the caps that are *bound*, and `capLabel` is how they are
*drawn*, so the three views cannot advertise a keystroke nothing runs.

### 2. `web/src/components/Footer.tsx` — the chips

Import `capLabel` beside `FOOTER_HINTS` and draw
`<Kbd key={key}>{capLabel(key)}</Kbd>`. The React key stays the cap
itself. Nothing else moves: the strip's order, its `max-md:hidden` and
the palette button are as they are.

### 3. `web/src/overlays/Keys.tsx` — the `?` overlay

Same one-line change inside `Row`: `<Kbd key={key}>{capLabel(key)}</Kbd>`.
"The footer chips, expanded" (10 §Overlays) stays literally true only
while both are drawn the same way.

### 4. `web/src/overlays/Palette.tsx` — the key column

The right-hand span becomes `{capLabel(action.key)}`. Import from
`../lib/keys`, which `overlays/Keys.tsx` already does.

**`keywords` keeps `action.key`**, unrelabelled: an operator who types
`D` into the palette must still find the row, and cmdk matches on the
keyword list. Add `capLabel(action.key)` to it as well so typing `⇧`
finds it too — one array, both spellings.

The column is a 40 px track and `⇧D` is two characters at `text-hint`,
so nothing is re-laid out; check it at `xlarge` on the type ramp all the
same (21 §Type scale).

### 5. `web/src/keys/useKeymap.ts` — one sentence, no behaviour

`capOf`'s docblock explains the `^p` notation. Add to it: the cap this
returns is the *dispatch* column, `event.key`, and what the footer, the
`?` overlay and the palette *draw* is `capLabel` of it (`lib/keys.ts`),
so `D` is bound and `⇧D` is shown without a second table.

No change to `handleKey`, `capOf`, `isTyping`, `inList`, the `a`/`d`
branch or `KeymapAction`.

### 6. `docs/v1/10-frontend.md` §Keyboard — the document moves with the tree

After the sentence "Delete moved from `d` to `D` so a `d` meant for
'deny' that lands one focus ring away cannot reach the delete confirm.",
add one sentence:

> Every place the map is drawn — the footer strip, the `?` overlay and
> the palette's key column — draws that cap as `⇧D`: a bare capital in
> an interface whose every other word is lowercase reads as the letter,
> and `d` is a row of this same map one keystroke away. The handler
> still dispatches on `event.key`, so the map's cap stays `D` — the
> modifier is drawn, not bound (D207).

Do **not** touch the map sentence itself: `` `D` (shift) delete run
(with confirm) `` is still exactly what is bound, and
`web/src/lib/__tests__/keys.test.ts` quotes that sentence and no other.
The new sentence must not be added to that quotation — its `⇧D` is not a
cap of the table and would fail the check that the table carries every
cap the section names.

The design mock draws `d` for this row (`docs/v1/design/Athanore.dc.html`,
`COMMANDS` and `KEYS`). It is not the reference here: D51 already moved
the binding off `d`, and the mock has no chip for what the app now
binds. Say so in the decision row, not in 10.

### 7. `docs/v1/15-decisions.md` — D207

One row, `**new (2026-09-10)**`, covering: (1) the reported bug was the
advertisement, not the binding — Shift+D, the overlay dispatch and
`DELETE /api/runs/{id}` all work in chromium, verified from six places
including the React Flow canvas and a held run, and the jsdom tests
already asserted it; (2) the label is derived from the cap (one
uppercase letter ⇒ a shift chip) rather than listed, so no second table
can drift; (3) `⇧` (U+21E7) over `shift+D`, because the palette's key
column is a 40 px track and the strip already draws `⏎`; (4) `d` stays
inert outside a request panel — D51 is the reason `D` exists and giving
`d` a hint, a toast or a fallthrough would spend the guard to save a
keystroke, and the app has no transient-notice surface for one anyway;
(5) the mock's `d` chip is superseded here, as its binding already was;
(6) the missing browser coverage is the reason nobody could answer the
question, and is added.

## Tests

Lowest layer that can express each thing (13 §Pyramid): the rule in
`lib/`, the drawing in the three views, and exactly one browser test —
because only a browser can say the keystroke reaches the endpoint and
the run comes back gone.

- **`web/src/lib/__tests__/keys.test.ts`** — a `capLabel` block: `'D'`
  is drawn `'⇧D'`; sweep every cap of `KEY_BINDINGS` and assert `D` is
  the only one `capLabel` changes today; `'^p'`, `'?'`, `'⏎'`, `'esc'`,
  `'tab'`, `'1–9'`, `'d'` and the four arrows come back unchanged. Both
  existing keycap-quotation tests, and
  `it('binds delete to D, never to the mock's d')` with its
  `expect(del?.keys).toEqual(['D'])`, must pass **unedited** — that they
  do is the point of putting the label outside the table.
- **`web/src/components/__tests__/Footer.test.tsx`** — change the one
  `HINTS` entry to `['⇧D', 'delete run']`, and rewrite
  `it('shows delete as D, not d')` as: the strip carries a chip reading
  `⇧D`, and no chip reads `d` or a bare `D`. The rewritten name should
  say why — the operator must not read the chip as `d`.
- **`web/src/overlays/__tests__/Keys.test.tsx`** — the row sweep
  compares rendered `kbd` text to `binding.keys`; it becomes
  `binding.keys.map(capLabel)`. That is the tightest statement of the
  invariant: what the panel draws is `capLabel` of the table, for every
  row. Add one assertion that the `delete-run` row still carries its
  note, so the words and the chip say shift together.
- **`web/src/overlays/__tests__/Palette.test.tsx`** — the `delete run`
  row's key column reads `⇧D`; a query of `D` still selects it (the
  keyword), and so does `⇧`; a keyless row still prints `—`.
- **`web/src/App.test.tsx`** — no edit expected. The two delete-key
  tests assert `onOpenOverlay` and are unaffected; the "binds every
  keycap of `lib/keys.ts` that names an action" test reads
  `binding.keys` and must keep passing untouched. If either needs a
  change, the label has leaked into the dispatch column — stop and fix
  that instead.
- **`web/e2e/keyboard.spec.ts`** — one new test, the coverage this key
  never had. Submit a `hold` run over the API, `select` it, then:
  1. the footer's delete chip reads `⇧D` (`footer kbd`, the locator
     `mobile.spec.ts` already uses);
  2. press `d` — `delete-run` stays hidden and the URL is unchanged;
  3. press `Shift+D` — `delete-run` is visible and `?overlay=delete` is
     in the URL;
  4. click its `delete run` button — the row goes, `rows()` is empty,
     `?run=` is gone from the URL, and no `delete-run-error` appears.
     `hold` parks at a request, so this exercises 04's cancel-then-delete
     rather than deleting something already finished.

  Keep it a separate test from the map sweep: it starts a run and deletes
  it, and the sweep asserts against two runs that stay.

## Verification

```sh
./scripts/test.sh
git diff --exit-code tests/snapshots web/src/api/gen
pnpm -C web exec playwright test keyboard.spec.ts mobile.spec.ts a11y.spec.ts --workers=1
```

`tests/snapshots` and `web/src/api/gen` must be byte-identical: nothing
here touches the wire.

Then by hand, `./scripts/run.sh` with a run or two: read the footer
strip and confirm the chip renders `⇧D` and not a missing-glyph box;
open `?` and the palette and confirm all three agree; press `d` and
confirm nothing happens; press `Shift+D` and delete a run. Check the
strip and the palette's key column at `small` and at `xlarge` on the
header's font-size chooser, and below the `md` breakpoint, where the
strip drops its chips and the palette is the whole route (21 §Narrow
layout).

## Done

- The footer strip, the `?` overlay and the palette's key column all
  draw the delete cap as `⇧D`; nothing anywhere draws a bare `D`.
- `KEY_BINDINGS`, `capOf`, `handleKey`, `PALETTE_COMMANDS` and
  `DeleteRun` are behaviourally unchanged, and the tests that assert
  what is *bound* pass unedited.
- `d` still reaches only the request panel that registered it (D51).
- `web/e2e/keyboard.spec.ts` proves in chromium that `Shift+D` opens the
  confirm, that `d` does not, and that confirming deletes the run and
  clears `?run=`.
- 10 §Keyboard carries the notation sentence; D207 recorded.
- Gate green; `tests/snapshots` and `web/src/api/gen` byte-identical.

## Out of scope (from the brief)

The delete operation itself and its endpoint (T017) — they work, and
this plan touches neither. The delete confirm's UI and copy. The
binding: `D` (shift) is 10 §Keyboard's and D51's, and neither the cap
nor the scope of `d` changes. Any other keybinding. No transient
notice, toast or hint for a key that did nothing — the app has no such
surface, `d` is required to be inert (D51), and inventing one here
would be a UX decision the brief does not ask for. No change to
`DeleteRun.tsx`'s `runId === undefined` branch: `D` with no run selected
is a disabled palette row and does nothing, which is the rule every
`needsRun` command follows (D175), and the brief scopes the report to a
selected run.

## Files

```
web/src/lib/keys.ts
web/src/components/Footer.tsx
web/src/overlays/Keys.tsx
web/src/overlays/Palette.tsx
web/src/keys/useKeymap.ts
web/src/lib/__tests__/keys.test.ts
web/src/components/__tests__/Footer.test.tsx
web/src/overlays/__tests__/Keys.test.tsx
web/src/overlays/__tests__/Palette.test.tsx
web/e2e/keyboard.spec.ts
docs/v1/10-frontend.md
docs/v1/15-decisions.md
```

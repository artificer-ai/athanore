# 21 — Design refresh: re-import, narrow viewports, type scale

The first post-1.0 feature set. Three things, one design source: the
Claude Design project **Athanore Coding Agent Dashboard** has moved on
since the 2026-09-05 import under [`design/`](design/README.md), and the
SPA follows it — the refreshed artifacts are re-imported and flow into
the app through the existing `gen:theme` pipeline; the dashboard becomes
usable on a phone-sized viewport by touch alone; and the operator can
choose the UI font size from within the app, with the whole type ramp
scaling coherently and the choice persisted per browser.

[`10-frontend.md`](10-frontend.md) remains the frontend spec. This
document is normative for the behaviour it adds; the tasks that build it
fold the deltas back into 10's affected sections (§Layout, §Design
system, §Accessibility and quality), each pointing here. Where this
document and 10 disagree afterwards, that is a bug in the fold, not a
choice.

## Scope

In scope: `docs/v1/design/` re-import and the regenerated theme; the
narrow-viewport layout and its touch operation; the font-size chooser
and the rem type ramp. All of it is presentation, per browser.

Out of scope, explicitly:

- **Any server or API change.** Font size and theme presentation are
  per-browser prefs (10 §Layout's split between the URL, `usePrefs` and
  the server). No `athanore.toml` key, no endpoint, no OpenAPI change,
  nothing under `athanore/`. `tests/snapshots/openapi.json` MUST be
  byte-identical after every task of this phase.
- A native or PWA app, offline support, service workers, or touch
  gestures beyond tap and scroll (no swipe navigation, no long-press).
- A second theme or light mode — unless the refreshed import defines one,
  which is a stop-and-ask (§Re-import), not something to absorb.
- Changes to the plugin contract: panel kinds, the manifest and
  `window.athanore` are untouched; plugin panels simply render inside the
  responsive detail pane.
- Reinstating anything D71 removed (CRT chrome, glows, the 2 px radius),
  unless the refreshed import brings it back — its own decision row.
- Reworking the desktop keyboard-first model. At and above the
  breakpoint the SPA is exactly what 10 specifies today.

## Re-import (normative)

- `docs/v1/design/Athanore.dc.html` and `docs/v1/design/nocturne.css`
  MUST be refreshed **verbatim** from the live Claude Design project
  (project `b7cb5192-4374-44e3-ae8f-2563907fa4ea`), and
  `docs/v1/design/README.md` MUST record the new import date. The
  curation the current import applied stands: `nocturne.css` keeps only
  the `:root` token block, the application overrides and the keyframes,
  as its header comment describes.
- Theme changes reach the app **only** through the pipeline:
  `pnpm -C web gen:theme` regenerates `web/src/styles/theme.css` and
  `tokens.gen.ts`, and `git diff --exit-code` after a second run proves
  the files are generated, not edited (`theme.test.ts` holds this in the
  gate already).
- **Diff discipline.** A reviewer diffing the old `nocturne.css` against
  the new one MUST find every difference either (a) in the regenerated
  theme, or (b) in a `15-decisions.md` row saying why the app does not
  follow it. The task that re-imports writes that mapping into its
  commit: one decision row per deviation, none for value changes that
  flow through.
- Every token or treatment the refresh changes MUST be reflected in
  10 §Design system (the tokens → shadcn table, the status colours, the
  type and density section) in the same task.
- **Stop-and-ask triggers** (D198). The re-import task MUST stop and ask
  the operator rather than proceed when the refreshed artifacts:
  add or remove an `--ath-status-*` name (D150's generator guard will
  refuse anyway); add a second theme or mode; change token *families*
  rather than values (new ramps, removed ramps); or prescribe a mobile
  layout or a font-size control that differs from this document. The
  last case supersedes §Narrow layout / §Type scale below only through
  the operator's ruling and a decision row — never silently.
- The re-import is blocked until the operator either runs
  `/design-login` once from an interactive session on this machine or
  places the refreshed files into `docs/v1/design/`. If the operator
  rules that no refreshed artifacts exist or none are wanted, the
  re-import task is dropped at approval and the rest of this document
  stands on the current import.

## Type scale (normative)

### The ramp becomes base-relative

The six type utilities of D150 keep their names, their single-class rule
and their treatments, but their sizes become fractions of the base
instead of absolute pixels. `gen-theme.mjs` MUST emit:

| Utility | Today | Becomes | At the default base |
|---|---|---|---|
| `text-metric` | 15 px / 500 | `calc(15rem / 12)` / 500 | 15 px |
| `text-body` | 12 px | `1rem` | 12 px |
| `text-row` | 11.5 px | `calc(11.5rem / 12)` | 11.5 px |
| `text-meta` | 11 px | `calc(11rem / 12)` | 11 px |
| `text-kicker` | 10.5 px | `calc(10.5rem / 12)` | 10.5 px |
| `text-hint` | 10 px | `calc(10rem / 12)` | 10 px |

`rem` reads the `<html>` font size, which is `var(--ath-font-size)`
(12 px today), so at the default setting every utility resolves to the
same pixels as before — the change is invisible until the base moves.
The `calc(<px>rem / 12)` form is exact (no rounded decimals), and the
`/ 12` denominator is the mock's base, a constant of the ramp, not a
read of the token. Line-height stays the unitless `1.5` and scales for
free.

**What scales is type, not density** (D195). Spacing, paddings, borders,
the 30 px collapsed rail, the pane-bar dots, the mock's pixel values in
10 §Type and density — all stay absolute. A component MUST NOT convert
its spacing to rem to "match"; the chooser changes text size, and the
layout absorbs it the way any text change is absorbed.

### The chooser

- Four fixed steps (D195), as multipliers of `--ath-font-size` so a
  refreshed base flows through them:

  | Step | `<html>` font-size | Today's base |
  |---|---|---|
  | `small` | `calc(var(--ath-font-size) * 11 / 12)` | 11 px |
  | `default` | `var(--ath-font-size)` | 12 px |
  | `large` | `calc(var(--ath-font-size) * 13.5 / 12)` | 13.5 px |
  | `xlarge` | `calc(var(--ath-font-size) * 15 / 12)` | 15 px |

- The choice lives in `usePrefs.fontSize`
  (`'small' | 'default' | 'large' | 'xlarge'`, default `'default'`),
  persisted in the `athanore.prefs` localStorage store like every other
  per-browser preference. Clearing site data therefore restores the
  design's default base. No URL state: a font size is personal, not part
  of what makes a view that view (10 §Layout).
- The SPA applies it as a `data-font-size` attribute on `<html>` —
  absent for `default` — written from the store on load before first
  paint and on every change. The generated `theme.css` maps the
  attribute to the sizes above in its app-type-base layer; no component
  reads the pref for styling.
- **The control** (D196): an icon-only text-size button in the header,
  beside `workflows`, with `aria-label="text size"`, opening a small
  popover (Radix Popover) with a radio group of the four steps, current
  one marked. The command palette lists the four as rows
  (`font size: small` …), so the keyboard-first path exists too. There
  is still no settings overlay in the SPA; this does not create one.
- The choice MUST visibly rescale the whole interface at once — metric
  values, table rows, kickers, hints, overlays, plugin panels — with no
  mixed-scale text at any step, MUST survive a full reload, and MUST
  apply on every load before the dashboard is interactive.

## Narrow layout (normative)

### One breakpoint

One breakpoint, Tailwind's `md` (min-width 768 px), splits the SPA into
its two layouts (D194). At `md` and above, 10 §Layout applies unchanged.
Below it — "narrow" — the SPA keeps the same header and footer regions
but shows **one** middle region at a time:

- `?run=` unset → the run list, full width.
- `?run=` set → the detail pane, full width.

Opening a run from the list writes `?run=` exactly as it does today;
"back" clears it. No new state: the stacked navigation rides the search
param that already is the selection (D152, D179), so a narrow view stays
linkable and a deep link to `?run=…&pane=…` opens on the detail.

The splitter is not mounted below the breakpoint. `listWidth` and
`listCollapsed` are inert there — kept, not cleared, so a phone visit
does not wipe the desktop geometry. The keyboard map stays fully bound
at every width (a phone with a hardware keyboard keeps every shortcut);
narrow adds touch routes and removes none.

At 390 px there MUST be no horizontal scroll on the page in any of the
flows below, and there SHOULD be none at 360 px — the narrow layout is
fluid, not a second fixed design. Strips that manage their own overflow
(the header's chip row) MAY scroll horizontally within themselves.

### Regions, narrow

- **Header**: wraps to two rows — brand, version, counts and the two
  buttons; then the workflow chips and the `/` filter as a horizontally
  scrollable strip. Nothing is dropped: `＋ new run` and `workflows`
  stay visible as touch targets. Interactive controls in the narrow
  chrome MUST have hit areas of at least 24×24 CSS px (WCAG 2.5.8);
  visual size may stay the mock's.
- **Run list**: the six-column grid gives way to a two-line row —
  line 1: TITLE (the run id when untitled) and the STATUS pill;
  line 2: `run id · workflow · node · age` in `text-meta`, with the `⚠`
  open-request glyph kept beside the node (10 §Attention). Same data,
  same query, same selection behaviour; tapping a row opens the detail.
  The list's footer strip keeps `n shown` and drops the `↑↓ select · ⏎
  focus detail` key hints.
- **Detail**: the pane bar's left slot shows a back control (`←` with
  an accessible "back to runs" label) in place of the list-collapse
  toggle, which has no meaning without the split; it clears `?run=`.
  The `◀`/`▶` pane buttons and the dots remain and are the touch route
  for cycling panes. The docked request panel and every pane render
  full-width; panes scroll vertically as they do today.
- **Footer**: the key-hint chips are hidden below the breakpoint —
  keycaps are noise on a touchscreen — and the footer keeps the
  `^p palette` button, relabelled `palette`, as a full-height touch
  target. The palette is the touch route to every operator action
  (D176: the keyboard map dispatches on the palette's rows, so the
  palette's catalogue is complete by construction).

### Overlays, narrow

Every overlay of 10 §Overlays MUST fit the narrow viewport: panel width
at most the viewport minus its backdrop margin, height at most `100dvh`
minus the same, content scrolling inside the panel. Specifically:

- **Command palette**: full-width under the header; rows are touch
  targets.
- **New run / edit**: the dialog spans the viewport width (minus
  margin); the workflow chip group wraps; `submit run` and `cancel` are
  reachable without scrolling past the fold when the form is empty.
- **Workflow library**: the two columns stack — the workflow list above,
  the source viewer below — as a full-screen sheet.
- **Task drawer**: a full-screen sheet.
- **Pickers, keys, delete-confirm, action**: sized to fit; the keys
  overlay keeps its desktop content (it documents the keyboard, which
  still exists) but MUST itself be scrollable and closable by touch.

Every overlay MUST be closable by touch: the backdrop tap closes (the
Radix behaviour today) and any overlay with a header carries its close
affordance as a real button. `esc` keeps working everywhere.

### Touch operation

By touch alone, on a 390 px viewport, an operator MUST be able to:
view the run list; open a run's detail; cycle its panes; answer an open
request (options, text and form kinds); and start a new run. Nothing in
those flows may be reachable only via a keyboard shortcut. Typing uses
the on-screen keyboard through ordinary focused inputs — that is not a
"keyboard shortcut".

## Gates (normative)

- **Playwright**: a mobile spec drives the five touch flows above at
  390×844 with `hasTouch` and `isMobile`, using `tap()` — not `click()`
  — for every activation (D197). One viewport is pinned; 360 px is
  covered by the fluid rule, not by a matrix.
- **axe**: the a11y gate of 10 §Accessibility and quality (no `serious`
  or `critical` violation, score ≥ 95) holds at the desktop viewport,
  at 390×844, and at the desktop viewport with `xlarge` selected.
- **The full gate** (`./scripts/test.sh`) is green after every task, and
  `tests/snapshots/openapi.json` is unchanged throughout the phase.
- The vitest layer covers what it can express below e2e (13 §Pyramid):
  the generated theme's ramp and attribute mapping, the prefs field and
  its application, the narrow run-list row, the back control's `?run=`
  write.

## Document updates

The tasks of this phase update, beside their code:

- 10 §Layout — the breakpoint and the narrow regions (pointer here).
- 10 §Design system §Type and density — the rem ramp and the chooser.
- 10 §Overlays — the narrow sizing rule.
- 10 §Accessibility and quality — the mobile and font-size axe runs.
- `design/README.md` — the new import date (re-import task).
- 15 — D194–D198 land with this document; deviations found during the
  re-import add their own rows.
- 16 Epic 7 and 17 Phase 7 — the tickets and tasks themselves.

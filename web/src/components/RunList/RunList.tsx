/**
 * The run list on the left.
 *
 * The mock's six-column grid, to the pixel: the column header, the
 * scrolling rows, and the footer strip that reports how many of them the
 * filter left. The 30 px rail it collapses to is `../Splitter`'s, and
 * the workflow chips and the `/` input are `./RunFilters`, which the
 * header strip renders — this is the grid and nothing else.
 *
 * Selection is the URL's: a click calls `onSelect`, the route writes
 * `?run=`, and the row that draws itself as selected is the one the
 * search parameter names. The list holds no selection of its own, so a
 * link into the app and a click inside it end in the same state.
 *
 * **Focus is one step past selection and is drawn as its own state.**
 * `⏎` picks the selected run up so that `↑`/`↓` move it in the dispatch
 * order (10 §Keyboard, D204); the shell decides whether a run is held
 * and names it in `focusedRun`, and the row it names keeps the
 * selection's tint and takes the second accent in its chrome — the left
 * border and an inset ring — rather than a fill of its own, which is
 * what keeps the status pill on it above the contrast floor. The footer
 * strip swaps its two hints to say which mode the list is in, in a live
 * region, because colour is never the only signal (10 §Accessibility and
 * quality).
 *
 * The 11.5 px row scale sits on the scrolling container and is inherited
 * rather than merged into a row's own classes: `cn` is tailwind-merge,
 * and it reads `text-row` as conflicting with the row's
 * `text-[var(--color-neutral-300)]` in the same call, keeping only the
 * last of the two (D157).
 *
 * Below the breakpoint the grid gives way to the two-line row of 21
 * §Narrow layout — TITLE and the status pill over `run id · workflow ·
 * node · age` — because six columns of 11 px text do not fit in a phone
 * and truncating five of them to nothing would be the same as dropping
 * them. It is a second row component and not a restyled one: the two
 * lines are a different shape, not a different width. Everything else
 * about the list is one thing at both widths — the same model, the same
 * `listbox`, the same selection handler, the same `⚠` (10 §Attention).
 * The column headings go with the columns, and the footer keeps
 * `n shown` and drops the key hints, which are not what a touch device
 * is operated by.
 */
import { useIsNarrow } from '../../lib/useIsNarrow'
import { cn } from '../../lib/utils'
import { useUi } from '../../store/ui'
import { StatusPill } from './StatusPill'
import type { RunListModel, RunRow } from './useRunList'

/** The mock's column template, to the pixel. */
const COLUMNS =
  'minmax(0, 108px) minmax(0, 104px) minmax(110px, 1fr) minmax(0, 84px) minmax(0, 92px) 46px'

const HEADINGS = ['RUN', 'WORKFLOW', 'TITLE', 'STATUS', 'NODE', 'AGE']

/** The glyph a run with unanswered requests carries after its node. */
const PENDING_GLYPH = '⚠'

/** The glyph a run of an unregistered workflow carries after its name. */
const UNREGISTERED_GLYPH = '⊘'

/** The separator between the narrow row's second line's four facts. */
const NARROW_SEPARATOR = '·'

/** What a row is, whichever shape it is drawn in. */
type RowProps = {
  row: RunRow
  zebra: boolean
  selected: boolean
  /** Whether `⏎` has picked this row up (10 §Keyboard). */
  focused: boolean
  onSelect: (runId: string) => void
}

/**
 * What the row is called: its title, or its id where there is none.
 *
 * The desktop grid can leave the TITLE column empty because the RUN
 * column beside it says which run this is; the narrow row's first line
 * is on its own, so an untitled run would be a status pill and nothing
 * else (21 §Narrow layout).
 */
function rowTitle(row: RunRow): string {
  return row.title === '' ? row.shortId : row.title
}

/**
 * The `⊘` of 10 §Attention, or nothing to draw: the run's workflow is not
 * registered on this server (22 §Remove, 08 §Runs).
 *
 * A glyph with a title rather than a word, because the WORKFLOW column
 * is 104 px and `⚠` is the precedent; it is an `img` with the word as
 * its name, which is what a glyph standing for a word is to a screen
 * reader — `aria-label` on a bare `span` is what axe refuses. It is
 * drawn in the muted colour and not a status tone: the run's status is
 * whatever it was, and the honest report is that nothing here can move
 * it until the workflow is back (D253).
 */
function Unregistered({ row }: { row: RunRow }) {
  if (!row.unregistered) return null
  return (
    <span
      role="img"
      className="ml-[4px] text-muted-foreground"
      title="this server has no workflow of that name"
      aria-label="unregistered"
      data-testid="run-unregistered"
    >
      {UNREGISTERED_GLYPH}
    </span>
  )
}

/** The `⚠` of 10 §Attention, or nothing to draw. */
function Pending({ row }: { row: RunRow }) {
  if (row.pendingRequests === 0) return null
  return (
    <span
      className="text-status-gate ml-[4px]"
      title={`${row.pendingRequests} waiting on you`}
    >
      {PENDING_GLYPH}
    </span>
  )
}

/**
 * The classes every row carries whatever its shape: the zebra stripe,
 * the selected tint and the accent bar down its left edge — and, on the
 * row `⏎` has picked up, the second accent in the chrome around it.
 *
 * **The mode is carried by the chrome and not by the fill.** A focused
 * row is always a selected row, so it keeps the selection's tint exactly
 * and changes its left border to `accent-2-400`, plus a 1 px inset ring
 * of the same colour around the whole row. A denser fill was the first
 * thing tried and is what a status pill cannot survive: `StatusPill` is
 * transparent and paints `text-status-*` straight onto the row, and
 * `color-mix(accent-2 22%, surface)` is light enough to take `fail`
 * (`#d9868f`) from 4.74:1 to 3.71:1 and `muted` (`#9397ab`) to 3.47:1 —
 * a `serious` axe violation, which 10 §Accessibility and quality
 * forbids outright, on a pill that is 10.5 px at normal weight and so is
 * never WCAG large text. The fix has to move the tint rather than the
 * text: `styles/theme.css` is generated from the design's tokens and
 * `--ath-status-fail` has no brighter sibling. Keeping the fill keeps
 * every one of the seven tones at the ratio it has today, and `⏎` may be
 * pressed on a `failed` or `cancelled` run (D204 (4), (5)).
 *
 * The border is written as one branch rather than two truthy classes, so
 * that tailwind-merge is never asked to pick between them (D157), and it
 * keeps its 2 px, so nothing in the grid shifts when the mode changes.
 */
function rowClasses(zebra: boolean, selected: boolean, focused: boolean): string {
  return cn(
    'w-full overflow-hidden border-l-2 border-l-transparent text-left text-[var(--color-neutral-300)] hover:bg-[var(--color-neutral-900)]',
    zebra && 'bg-zebra',
    selected && 'bg-[color-mix(in_srgb,var(--color-accent)_12%,var(--color-surface))]',
    focused
      ? 'border-l-[var(--color-accent-2-400)] inset-ring-1 inset-ring-[var(--color-accent-2-400)]'
      : selected && 'border-l-[var(--color-accent)]',
  )
}

function Row({ row, zebra, selected, focused, onSelect }: RowProps) {
  // `--muted-foreground` is 4.43:1 on the selected row's accent tint,
  // which is under AA for text this size; one step brighter clears it.
  // The tint itself is the mock's and is not touched — these three
  // columns are muted by the SPA's choice, not the mock's, so this is
  // the half of the pair that may move (10 §Accessibility and quality).
  // A focused row is a selected row wearing different chrome, so it is
  // the same tint and takes the same step, from the same branch.
  const muted = selected ? 'text-[var(--color-neutral-400)]' : 'text-muted-foreground'

  return (
    <button
      type="button"
      role="option"
      aria-selected={selected}
      data-selected={selected}
      // A `data-*` attribute and not ARIA: `option` takes
      // `aria-selected` and nothing else that means this, and
      // `aria-grabbed` is deprecated. What announces the mode is the
      // footer strip's live region.
      data-run-focused={focused}
      title={row.id}
      onClick={() => onSelect(row.id)}
      style={{ gridTemplateColumns: COLUMNS }}
      className={cn(
        'grid items-center gap-[8px] px-[12px] py-[4px]',
        rowClasses(zebra, selected, focused),
      )}
    >
      <span className={cn('truncate', muted)}>{row.shortId}</span>
      <span className="truncate text-[var(--color-accent-2-400)]">
        {row.workflow}
        <Unregistered row={row} />
      </span>
      <span className="truncate">{row.title}</span>
      <StatusPill status={row.status} tone={row.tone} className="justify-self-start" />
      <span className={cn('truncate', muted)}>
        {row.node}
        <Pending row={row} />
      </span>
      <span className={cn('text-right', muted)}>{row.age}</span>
    </button>
  )
}

/**
 * The same row below the breakpoint: two lines, four facts on the
 * second (21 §Narrow layout).
 *
 * The separators are `aria-hidden`, because a screen reader reading
 * "01H4 dot probe dot draft dot 4m" is being read punctuation; the
 * `title` attribute carries the whole id here as it does on the grid.
 */
function NarrowRow({ row, zebra, selected, focused, onSelect }: RowProps) {
  // The same one step of contrast the grid takes on a selected row, for
  // the same reason (10 §Accessibility and quality).
  const muted = selected ? 'text-[var(--color-neutral-400)]' : 'text-muted-foreground'

  return (
    <button
      type="button"
      role="option"
      aria-selected={selected}
      data-selected={selected}
      data-run-focused={focused}
      data-narrow
      title={row.id}
      onClick={() => onSelect(row.id)}
      className={cn(
        'flex flex-col gap-[3px] px-[12px] py-[8px]',
        rowClasses(zebra, selected, focused),
      )}
    >
      <span className="flex w-full items-center gap-[8px]">
        <span data-testid="narrow-title" className="min-w-0 flex-1 truncate">
          {rowTitle(row)}
        </span>
        <StatusPill status={row.status} tone={row.tone} />
      </span>

      <span
        data-testid="narrow-meta"
        className={cn('text-meta flex w-full min-w-0 items-center gap-[5px]', muted)}
      >
        <span className="flex-none">{row.shortId}</span>
        <span aria-hidden className="flex-none">
          {NARROW_SEPARATOR}
        </span>
        <span className="flex-none truncate text-[var(--color-accent-2-400)]">
          {row.workflow}
          <Unregistered row={row} />
        </span>
        <span aria-hidden className="flex-none">
          {NARROW_SEPARATOR}
        </span>
        <span className="min-w-0 flex-1 truncate">
          {row.node}
          <Pending row={row} />
        </span>
        <span aria-hidden className="flex-none">
          {NARROW_SEPARATOR}
        </span>
        <span className="flex-none">{row.age}</span>
      </span>
    </button>
  )
}

/**
 * What the body shows when it has no rows to show.
 *
 * A failed request says so rather than reading as an empty list: "no
 * runs" and "we could not ask" are different facts (02 §Real data only),
 * and only one of them is the operator's cue to look at the server.
 */
function Empty({ model }: { model: RunListModel }) {
  if (model.isPending) {
    return (
      <p role="status" className="text-meta px-[12px] py-[8px] text-muted-foreground">
        loading runs…
      </p>
    )
  }
  if (model.isError) {
    return (
      <p role="status" className="text-status-fail text-meta px-[12px] py-[8px]">
        could not load runs
      </p>
    )
  }
  return (
    <p className="text-meta px-[12px] py-[8px] text-muted-foreground">
      {model.total === 0 ? 'no runs yet' : 'no runs match the filter'}
    </p>
  )
}

export function RunList({
  model,
  selected,
  focusedRun,
  onSelect,
}: {
  model: RunListModel
  /** The run `?run=` names, if any. */
  selected: string | undefined
  /**
   * The run `⏎` has picked up, if any (10 §Keyboard).
   *
   * The shell decides it and hands it down already guarded: it is only
   * ever the selected run, only while that row is in `model.rows`, and
   * only at `md` and above (`../../App.tsx`, D204 (2)).
   */
  focusedRun?: string | undefined
  onSelect: (runId: string) => void
}) {
  const holding = focusedRun !== undefined
  const focused = useUi((s) => s.focus === 'list')
  const setFocus = useUi((s) => s.setFocus)
  const narrow = useIsNarrow()

  return (
    <section
      aria-label="runs"
      data-region="list"
      data-focused={focused}
      onMouseDown={() => setFocus('list')}
      onFocusCapture={() => setFocus('list')}
      className="flex h-full min-h-0 min-w-0 flex-col border-r border-border data-[focused=true]:border-r-[var(--color-accent-800)] max-md:flex-1 max-md:border-r-0"
    >
      {/* The headings go with the columns: a two-line row has none to
          head, and a strip reading RUN WORKFLOW TITLE over rows shaped
          like neither would be a legend for a grid that is not there. */}
      <div
        className="text-hint bg-chrome grid gap-[8px] overflow-hidden border-b border-border px-[12px] py-[6px] tracking-[0.1em] text-muted-foreground max-md:hidden"
        style={{ gridTemplateColumns: COLUMNS }}
      >
        {HEADINGS.map((heading) => (
          <span key={heading} className={heading === 'AGE' ? 'text-right' : undefined}>
            {heading}
          </span>
        ))}
      </div>

      {/* The `listbox` is drawn only when it has `option`s to hold: a
          role that requires particular children and is given a status
          paragraph instead is `aria-required-children`, and a screen
          reader is told there is a list box with nothing in it rather
          than the sentence that says why (10 §Accessibility and
          quality). */}
      <div className="text-row min-h-0 flex-1 overflow-x-hidden overflow-y-auto">
        {model.rows.length === 0 ? (
          <Empty model={model} />
        ) : (
          <div role="listbox" aria-label="run rows">
            {model.rows.map((row, index) => {
              const props = {
                row,
                zebra: index % 2 === 1,
                selected: row.id === selected,
                focused: row.id === focusedRun,
                onSelect,
              }
              return narrow ? (
                <NarrowRow key={row.id} {...props} />
              ) : (
                <Row key={row.id} {...props} />
              )
            })}
          </div>
        )}
      </div>

      <div className="text-hint bg-chrome flex gap-[14px] border-t border-border px-[12px] py-[5px] text-muted-foreground">
        <span data-testid="rows-shown">{model.rows.length} shown</span>
        {/* Keycaps are noise on a touchscreen; the keys they name stay
            bound at every width (21 §Narrow layout). The pair is a live
            region because it is what says which mode the arrows are in,
            and colour is never the only signal (10 §Accessibility and
            quality); `n shown` stays outside it, being neither. */}
        <span
          role="status"
          data-testid="list-hints"
          className="flex gap-[14px] max-md:hidden"
        >
          <span>{holding ? '↑↓ move run' : '↑↓ select'}</span>
          <span>{holding ? '⏎/esc done' : '⏎ focus run'}</span>
        </span>
      </div>
    </section>
  )
}

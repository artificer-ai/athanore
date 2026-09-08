/**
 * The run list on the left (`docs/v1/10-frontend.md` §Layout).
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
 * The 11.5 px row scale sits on the scrolling container and is inherited
 * rather than merged into a row's own classes: `cn` is tailwind-merge,
 * and it reads `text-row` as conflicting with the row's
 * `text-[var(--color-neutral-300)]` in the same call, keeping only the
 * last of the two (D157).
 */
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

function Row({
  row,
  zebra,
  selected,
  onSelect,
}: {
  row: RunRow
  zebra: boolean
  selected: boolean
  onSelect: (runId: string) => void
}) {
  return (
    <button
      type="button"
      role="option"
      aria-selected={selected}
      data-selected={selected}
      title={row.id}
      onClick={() => onSelect(row.id)}
      style={{ gridTemplateColumns: COLUMNS }}
      className={cn(
        'grid w-full items-center gap-[8px] overflow-hidden border-l-2 border-l-transparent px-[12px] py-[4px] text-left text-[var(--color-neutral-300)] hover:bg-[var(--color-neutral-900)]',
        zebra && 'bg-zebra',
        selected &&
          'border-l-[var(--color-accent)] bg-[color-mix(in_srgb,var(--color-accent)_12%,var(--color-surface))]',
      )}
    >
      <span className="truncate text-muted-foreground">{row.shortId}</span>
      <span className="truncate text-[var(--color-accent-2-400)]">{row.workflow}</span>
      <span className="truncate">{row.title}</span>
      <StatusPill status={row.status} tone={row.tone} className="justify-self-start" />
      <span className="truncate text-muted-foreground">
        {row.node}
        {row.pendingRequests > 0 && (
          <span
            className="text-status-gate ml-[4px]"
            title={`${row.pendingRequests} waiting on you`}
          >
            {PENDING_GLYPH}
          </span>
        )}
      </span>
      <span className="text-right text-muted-foreground">{row.age}</span>
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
  onSelect,
}: {
  model: RunListModel
  /** The run `?run=` names, if any. */
  selected: string | undefined
  onSelect: (runId: string) => void
}) {
  const focused = useUi((s) => s.focus === 'list')
  const setFocus = useUi((s) => s.setFocus)

  return (
    <section
      aria-label="runs"
      data-region="list"
      data-focused={focused}
      onMouseDown={() => setFocus('list')}
      onFocusCapture={() => setFocus('list')}
      className="flex h-full min-h-0 min-w-0 flex-col border-r border-border data-[focused=true]:border-r-[var(--color-accent-800)]"
    >
      <div
        className="text-hint bg-chrome grid gap-[8px] overflow-hidden border-b border-border px-[12px] py-[6px] tracking-[0.1em] text-muted-foreground"
        style={{ gridTemplateColumns: COLUMNS }}
      >
        {HEADINGS.map((heading) => (
          <span key={heading} className={heading === 'AGE' ? 'text-right' : undefined}>
            {heading}
          </span>
        ))}
      </div>

      <div
        role="listbox"
        aria-label="run rows"
        className="text-row min-h-0 flex-1 overflow-x-hidden overflow-y-auto"
      >
        {model.rows.length === 0 ? (
          <Empty model={model} />
        ) : (
          model.rows.map((row, index) => (
            <Row
              key={row.id}
              row={row}
              zebra={index % 2 === 1}
              selected={row.id === selected}
              onSelect={onSelect}
            />
          ))
        )}
      </div>

      <div className="text-hint bg-chrome flex gap-[14px] border-t border-border px-[12px] py-[5px] text-muted-foreground">
        <span data-testid="rows-shown">{model.rows.length} shown</span>
        <span>↑↓ select</span>
        <span>⏎ focus detail</span>
      </div>
    </section>
  )
}

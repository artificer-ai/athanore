/**
 * The overview pane: what a run cost, what it is, and what it did
 * (`docs/v1/10-frontend.md` §Panes item 1, and the mock's `isOverview`
 * block in `docs/v1/design/Athanore.dc.html`).
 *
 * Five sections, the mock's four in its order with one inserted — the
 * STATS tiles with the per-node token bars under them, the two-column
 * `kv` meta grid, the full-width TITLE and DESCRIPTION block, the NODES
 * table, and the OUTPUTS list a fanned-out run adds — followed by
 * whatever `placement="card"` panels the manifest contributed (09
 * §Slots), which the pane host hands in as `cards`.
 *
 * **The block is where 10 §Panes' TITLE and DESCRIPTION went** (15,
 * D208). They are meta fields like the other six, but the grid that
 * draws those is `repeat(auto-fit, minmax(240px, 1fr))` — the right
 * shape for a run id or an age, the wrong one for a description, which
 * is written in a textarea (10 §Overlays) and can be a paragraph. In a
 * 240 px column it wrapped into a narrow stack that pushed NODES down
 * the pane while the pane's width sat empty beside it, so the two get a
 * section of their own where each label sits over its value and the
 * value has the pane's full width.
 *
 * **Two sources, and neither is a second opinion of the other.** The
 * tiles, the bars, the meta and the node rows all come from the
 * `overview` builtin's route, which reads them through `services.run.
 * detail()` — the same read `GET /api/runs/{id}` makes, so a tile and
 * `RunDetail.stats` cannot drift (09 §Context and scopes). What this
 * pane asks `GET /api/runs/{id}` for is what the route does not send and
 * could not: the attempt ids a NODES row opens the drawer on, the nodes
 * the run is in right now, and the terminal branches the OUTPUTS list
 * draws. It recomputes nothing the route already answered.
 *
 * **Nothing is zero-filled.** The route omits what it does not know (01
 * §Real data only) and this renderer keeps it omitted: a metric with no
 * value is absent, SESSION is missing until an agent has run, a node
 * with no stats entry gets no bar, and a span nobody measured is `—`.
 * The formatting rules are `./overview.ts`.
 */
import type { ReactNode } from 'react'

import type { RunDetail } from '../../api/gen/types.gen'
import { taskTone, toneClass, tonePulses } from '../../components/RunList'
import { cn } from '../../lib/utils'
import { KvPane } from './KvPane'
import { MetricGrid } from './MetricGrid'
import { formatValue } from './format'
import {
  formatAbout,
  formatCount,
  formatMeta,
  formatMetric,
  formatSeconds,
  latestTaskOf,
  outputLines,
  tokenBars,
  type TokenBar,
} from './overview'
import { useRunDetail } from './run'
import type { OverviewData, TableColumn, TableRow } from './shape'

/**
 * The mock's NODES template, for the five columns the builtin's route
 * declares.
 *
 * The mock's pixels, with one column widened: it drew run statuses
 * (`done`, `running`), and this table draws *attempt* statuses, of which
 * `in_progress` and `dead_letter` do not fit its 80 px (15, D162).
 * Colour is never the only signal (10 §Accessibility), so the word has
 * to be readable.
 */
const NODE_COLUMNS = 'minmax(60px, 1fr) 34px minmax(0, 96px) minmax(0, 76px) minmax(0, 58px)'

/** Column kinds whose values read right-aligned, as the mock draws them. */
const NUMERIC: ReadonlySet<string> = new Set(['number', 'duration'])

/** One pane section: the mock's `12px 14px` over a neutral-900 rule. */
function Section({
  label,
  children,
  testId,
}: {
  /** The section kicker (`STATS`, `NODES`); the meta grid has none. */
  label?: string
  children: ReactNode
  testId?: string
}) {
  return (
    <section
      {...(testId === undefined ? {} : { 'data-testid': testId })}
      {...(label === undefined ? {} : { 'aria-label': label })}
      className="border-b border-[var(--color-neutral-900)] px-[14px] py-[12px] last:border-b-0"
    >
      {label !== undefined && (
        <h2 className="text-hint mb-[8px] tracking-[0.14em] text-muted-foreground">
          {label}
        </h2>
      )}
      {children}
    </section>
  )
}

/**
 * The per-node token bars (10 §Panes: "accent for the active node,
 * accent-700 otherwise", scaled to the largest node total).
 *
 * The colours are written out rather than built from `active`, because
 * Tailwind only generates a utility it can see the name of in the
 * source.
 */
function TokenBars({ bars }: { bars: readonly TokenBar[] }) {
  if (bars.length === 0) return null

  return (
    <ul data-testid="token-bars" className="mt-[12px] flex flex-col gap-[3px]">
      {bars.map((bar) => (
        <li
          key={bar.node}
          data-node={bar.node}
          data-active={bar.active}
          className="grid grid-cols-[minmax(0,84px)_minmax(60px,1fr)_minmax(0,70px)] items-center gap-[8px]"
        >
          <span className="text-meta truncate text-right text-muted-foreground">
            {bar.node}
          </span>
          <span className="block h-[8px] overflow-hidden rounded-lg bg-[var(--color-neutral-900)]">
            <span
              data-testid="token-bar-fill"
              // The width is data, so it is a style and not a class:
              // Tailwind cannot generate a utility per percentage.
              style={{ width: `${String(bar.percent)}%` }}
              className={cn(
                'block h-full',
                bar.active
                  ? 'bg-[var(--color-accent)]'
                  : 'bg-[var(--color-accent-700)]',
              )}
            />
          </span>
          <span className="text-meta truncate text-right text-muted-foreground">
            {bar.count}
          </span>
        </li>
      ))}
    </ul>
  )
}

/** One NODES cell, formatted by the column kind its route declared. */
function Cell({ column, row }: { column: TableColumn; row: TableRow }) {
  const value = row[column.key]

  if (column.kind === 'status') {
    // The mock's own STATUS cell: the word in its status colour, not the
    // outlined pill the run list draws. A pill inside a 34 px-gapped row
    // would be a second frame inside the table's (10 §Status colours).
    const status = formatValue(value)
    const tone = taskTone(status)
    return (
      <span
        title={status}
        className={cn(
          'truncate tracking-[0.06em]',
          toneClass(tone),
          tonePulses(tone) && 'animate-ath-pulse',
        )}
      >
        {status}
      </span>
    )
  }

  const text =
    column.kind === 'duration'
      ? formatSeconds(value)
      : column.kind === 'number'
        ? formatCount(value)
        : formatValue(value)

  return (
    <span
      className={cn(
        'truncate',
        NUMERIC.has(column.kind ?? '')
          ? 'text-right text-muted-foreground'
          : 'text-[var(--color-neutral-300)]',
      )}
    >
      {text}
    </span>
  )
}

/**
 * The NODES table: one row per node the run has entered, zebra-striped,
 * each row opening that node's most recent attempt in the task drawer.
 *
 * A `button` rather than a table row for the reason the run list's rows
 * are buttons: the row *is* the control, so it is reachable by keyboard
 * and announced as one without a `role` bolted onto a `tr`. A run whose
 * attempts have not arrived yet — `GET /api/runs/{id}` still in flight —
 * draws the same rows without the click, rather than opening a drawer on
 * a task id this pane does not have.
 */
function NodesTable({
  columns,
  rows,
  detail,
  onOpenTask,
}: {
  columns: readonly TableColumn[]
  rows: readonly TableRow[]
  detail: RunDetail | undefined
  onOpenTask?: ((taskId: number) => void) | undefined
}) {
  const template =
    columns.length === 5 ? NODE_COLUMNS : `repeat(${String(columns.length)}, minmax(0, 1fr))`

  if (rows.length === 0) {
    return (
      <p className="text-row text-muted-foreground" role="status">
        no attempts yet
      </p>
    )
  }

  return (
    <>
      <div
        className="text-hint grid gap-[6px] overflow-hidden px-[8px] pb-[5px] tracking-[0.06em] text-muted-foreground"
        style={{ gridTemplateColumns: template }}
      >
        {columns.map((column) => (
          <span
            key={column.key}
            className={NUMERIC.has(column.kind ?? '') ? 'text-right' : undefined}
          >
            {column.label ?? column.key}
          </span>
        ))}
      </div>

      <div
        data-testid="node-rows"
        className="text-row overflow-hidden rounded-lg border border-[var(--color-neutral-900)]"
      >
        {rows.map((row, index) => {
          const node = String(row['node'] ?? '')
          const taskId = latestTaskOf(detail?.tasks, node)
          return (
            <button
              key={node === '' ? index : node}
              type="button"
              data-node={node}
              disabled={taskId === undefined || onOpenTask === undefined}
              onClick={() => {
                if (taskId !== undefined) onOpenTask?.(taskId)
              }}
              style={{ gridTemplateColumns: template }}
              className={cn(
                'grid w-full items-center gap-[6px] overflow-hidden px-[8px] py-[4px] text-left enabled:hover:bg-[var(--color-neutral-900)]',
                index % 2 === 1 && 'bg-zebra',
              )}
            >
              {columns.map((column) => (
                <Cell key={column.key} column={column} row={row} />
              ))}
            </button>
          )
        })}
      </div>
    </>
  )
}

export function Overview({
  data,
  runId,
  onOpenTask,
  cards,
}: {
  /** The `overview` builtin's answer (09 §Panel kinds, plus `meta`). */
  data: OverviewData
  /** The run in scope; the pane host resolved it before drawing this. */
  runId: string | undefined
  /** Open an attempt in the task drawer (10 §Overlays). */
  onOpenTask?: ((taskId: number) => void) | undefined
  /** The `placement="card"` panels, appended below (09 §Slots). */
  cards?: ReactNode
}) {
  const detail = useRunDetail(runId)

  const metrics = data.metrics.map(formatMetric)
  const meta = formatMeta(data.meta)
  const about = formatAbout(data.meta)
  const columns = data.table?.columns ?? []
  const rows = data.table?.rows ?? []
  const bars = tokenBars(rows, detail?.current_nodes ?? [])
  const outputs = outputLines(detail?.outputs)

  return (
    <div
      data-testid="pane-overview"
      className="min-h-0 flex-1 overflow-x-hidden overflow-y-auto"
    >
      <Section label="STATS">
        <MetricGrid metrics={metrics} label="run totals" />
        <TokenBars bars={bars} />
      </Section>

      {Object.keys(meta).length > 0 && (
        <Section testId="overview-meta">
          <KvPane data={meta} />
        </Section>
      )}

      {about !== null && (
        <Section testId="overview-about">
          <dl className="flex flex-col gap-[10px]">
            {about.title !== null && (
              <div>
                <dt className="text-hint tracking-[0.1em] text-muted-foreground">
                  TITLE
                </dt>
                <dd className="text-body [overflow-wrap:anywhere] text-[var(--color-neutral-300)]">
                  {about.title}
                </dd>
              </div>
            )}
            <div>
              <dt className="text-hint tracking-[0.1em] text-muted-foreground">
                DESCRIPTION
              </dt>
              <dd className="text-body [overflow-wrap:anywhere] text-[var(--color-neutral-300)]">
                {about.description}
              </dd>
            </div>
          </dl>
        </Section>
      )}

      {data.table !== undefined && (
        <Section label="NODES">
          <NodesTable
            columns={columns}
            rows={rows}
            detail={detail}
            onOpenTask={onOpenTask}
          />
        </Section>
      )}

      {outputs.length > 0 && (
        <Section label="OUTPUTS">
          <dl data-testid="overview-outputs" className="flex flex-col gap-[6px]">
            {outputs.map((output) => (
              <div
                key={output.taskId}
                className="grid grid-cols-[minmax(0,120px)_minmax(0,1fr)] items-start gap-[10px]"
              >
                <dt className="text-row truncate text-[var(--color-accent-2-400)]">
                  {output.node}
                </dt>
                <dd className="text-row [overflow-wrap:anywhere] text-[var(--color-neutral-300)]">
                  {output.preview}
                </dd>
              </div>
            ))}
          </dl>
        </Section>
      )}

      {cards}
    </div>
  )
}

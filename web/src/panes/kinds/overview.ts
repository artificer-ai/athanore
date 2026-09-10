/**
 * How the overview pane reads what its source sent
 * (`docs/v1/10-frontend.md` §Panes — "Field sources").
 *
 * Separate from `./Overview.tsx` for the reason `./format.ts` is
 * separate from the renderers: a component module that also exports
 * functions is one React Fast Refresh cannot update in place
 * (`.oxlintrc.json`, `react/only-export-components`).
 *
 * Everything here is the same rule twice over. **A value is formatted by
 * the field it is, not by its type**: `612,884` is a token count and
 * `$0.2914` is money, and the generic `formatValue` of `./format.ts`
 * would print both as bare numbers because it does not know which is
 * which. And **nothing is invented**: a field the source omitted stays
 * omitted, a bar is drawn only for a node that reported a number, and a
 * span nobody measured reads as `—` rather than as a zero (01 §Real data
 * only).
 */
import { humaniseElapsed } from '../../components/RunList'
import type { RunOutput, TaskView } from '../../api/gen/types.gen'
import { formatValue } from './format'
import type { Metric, TableRow } from './shape'

/** How many characters of the agent session the SESSION field shows. */
export const SESSION_LENGTH = 8

/** The narrowest a token bar is drawn, so a small one is still visible. */
export const MIN_BAR_PERCENT = 3

/** How much of a terminal value the OUTPUTS list previews. */
export const PREVIEW_LENGTH = 120

/** What a field with nothing behind it reads as, as everywhere else. */
const DASH = '—'

/** The two meta fields the grid is the wrong shape for (10 §Panes). */
const TITLE_KEY = 'TITLE'
const DESCRIPTION_KEY = 'DESCRIPTION'

/**
 * `612,884` — a count, grouped.
 *
 * `en-US` rather than the browser's locale: the mock's separators are
 * the app's, and a page that grouped with spaces in one country and
 * commas in another would not be the design.
 */
const GROUPED = new Intl.NumberFormat('en-US')

/** A count, or `—` when the number is not one. */
export function formatCount(value: unknown): string {
  return typeof value === 'number' && Number.isFinite(value)
    ? GROUPED.format(value)
    : formatValue(value)
}

/**
 * `$0.2914` — money, to the mock's four decimal places.
 *
 * Agent costs run to fractions of a cent per attempt, so two places
 * would round most of a run's tiles to `$0.00`.
 */
export function formatCost(value: unknown): string {
  return typeof value === 'number' && Number.isFinite(value)
    ? `$${value.toFixed(4)}`
    : formatValue(value)
}

/**
 * `246s` — a span in seconds, as the mock writes both the DURATION tile
 * and the NODES table's DUR column (15, D161).
 *
 * One decimal below ten seconds, because a node that took 0.4 s did not
 * take none; whole seconds above it, because the tenth of a second in
 * `3944.2s` is noise.
 */
export function formatSeconds(value: unknown): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return formatValue(value)
  const seconds = Math.max(0, value)
  return seconds < 10 ? `${String(Number(seconds.toFixed(1)))}s` : `${String(Math.round(seconds))}s`
}

/**
 * One of the four tiles, formatted by its label (10 §Panes).
 *
 * A label this build does not know — a metric a later Athanore adds — is
 * printed by the generic formatter rather than dropped: an unknown field
 * is still the server's data.
 */
export function formatMetric(metric: Metric): Metric {
  switch (metric.label) {
    case 'TOKENS':
      return { label: metric.label, value: formatCount(metric.value) }
    case 'COST':
      return { label: metric.label, value: formatCost(metric.value) }
    case 'DURATION':
      return { label: metric.label, value: formatSeconds(metric.value) }
    default:
      return { label: metric.label, value: formatValue(metric.value) }
  }
}

/**
 * The `kv` meta grid, formatted field by field (10 §Panes).
 *
 * The source sends AGE as seconds and SESSION whole; 10 asks for the
 * mock's humanised age and for eight characters of the session, and
 * both of those are the renderer's decision rather than the route's.
 * Key order is the source's own, which is the order 10 lists the fields
 * in, so a field this build has no rule for still lands in its place.
 *
 * **TITLE and DESCRIPTION are deliberately not here** — a function
 * called `formatMeta` that drops two of the meta keys is a thing to put
 * back by accident. They are {@link formatAbout}'s, because the grid
 * they used to sit in is `minmax(240px, 1fr)` wide and a description is
 * written in a textarea and can be a paragraph (15, D208); the block
 * that draws them has the pane's whole width.
 */
export function formatMeta(meta: Record<string, unknown>): Record<string, string> {
  const out: Record<string, string> = {}
  for (const [key, value] of Object.entries(meta)) {
    if (key === TITLE_KEY || key === DESCRIPTION_KEY) continue

    if (key === 'AGE') {
      out[key] =
        typeof value === 'number' && Number.isFinite(value)
          ? humaniseElapsed(value * 1000)
          : formatValue(value)
    } else if (key === 'SESSION') {
      out[key] =
        typeof value === 'string' ? value.slice(0, SESSION_LENGTH) : formatValue(value)
    } else if (key === 'AGENTS') {
      out[key] = formatCount(value)
    } else {
      out[key] = formatValue(value)
    }
  }
  return out
}

/** The two fields the grid is the wrong shape for (10 §Panes). */
export type RunAbout = {
  /** The run's title, or `null` when the source sent none. */
  title: string | null
  /** The run's description, or `—` (10 §Panes, D161). */
  description: string
}

/**
 * The full-width TITLE and DESCRIPTION block, or nothing at all.
 *
 * DESCRIPTION is the one field drawn whether or not the source sent it:
 * 10 §Panes says it "is the run's, or `—`", against the SESSION and
 * AGENTS beside it, which it says are omitted until an agent has run.
 * TITLE is not dashed — 10 gives the dash to DESCRIPTION and to nothing
 * else, and the builtin's route always sends TITLE, so an absent one
 * came from a panel that meant not to have one, and its row is dropped.
 *
 * `null` when the source sent **neither** key: an `overview`-kind panel
 * a plugin declares need not be about a run at all (09 §Panel kinds),
 * and drawing `TITLE —` and `DESCRIPTION —` under one would be this
 * renderer inventing two fields nobody sent (01 §Real data only).
 *
 * Both values go through `formatValue` and nothing else — no preview,
 * no truncation, no re-wrapping. The block is a layout, not a formatter.
 */
export function formatAbout(meta: Record<string, unknown>): RunAbout | null {
  const hasTitle = TITLE_KEY in meta
  if (!hasTitle && !(DESCRIPTION_KEY in meta)) return null
  return {
    title: hasTitle ? formatValue(meta[TITLE_KEY]) : null,
    description: DESCRIPTION_KEY in meta ? formatValue(meta[DESCRIPTION_KEY]) : DASH,
  }
}

/** One per-node token bar: what it says, how long it is, and its colour. */
export type TokenBar = {
  node: string
  /** The count itself, grouped — the bar's right-hand column. */
  count: string
  /** Its length as a percentage of the largest node's, `1`–`100`. */
  percent: number
  /** Whether the run is in this node right now (accent, not accent-700). */
  active: boolean
}

/**
 * The bars, from the NODES rows the same table draws (10 §Panes — "token
 * bars scale to the largest node total in the run").
 *
 * **A node with no `tokens` key gets no bar.** The route omits the key
 * for a node no agent reported on (`overview.py`), and a zero-length bar
 * would be this renderer claiming it spent nothing. A node that really
 * reported `0` keeps its bar, at the minimum width.
 */
export function tokenBars(
  rows: readonly TableRow[],
  activeNodes: readonly string[],
): TokenBar[] {
  const counted = rows.filter(
    (row) => typeof row['tokens'] === 'number' && Number.isFinite(row['tokens']),
  )
  const totals = counted.map((row) => row['tokens'] as number)
  const largest = Math.max(0, ...totals)

  return counted.map((row, index) => {
    const total = totals[index] ?? 0
    const scaled = largest > 0 ? Math.round((total / largest) * 100) : 0
    return {
      node: String(row['node'] ?? ''),
      count: GROUPED.format(total),
      percent: Math.max(MIN_BAR_PERCENT, scaled),
      active: activeNodes.includes(String(row['node'] ?? '')),
    }
  })
}

/**
 * The attempt a NODES row opens in the task drawer: the node's most
 * recent one.
 *
 * The row collapses every attempt of its node into one line whose STATUS
 * is the latest attempt's (`overview.py`), so the drawer the operator
 * expects from clicking it is that same attempt. `RunDetail.tasks` is
 * oldest first (08 §Runs), so the last match is it.
 */
export function latestTaskOf(
  tasks: readonly TaskView[] | undefined,
  node: string,
): number | undefined {
  let latest: number | undefined
  for (const task of tasks ?? []) if (task.node === node) latest = task.id
  return latest
}

/** One line of the OUTPUTS list: which branch ended, and with what. */
export type OutputLine = {
  /** Stable within the list: a terminal attempt appears once. */
  taskId: number
  /** The node, with its branch keys when the run fanned out. */
  node: string
  /** The value, printed and cut to {@link PREVIEW_LENGTH}. */
  preview: string
}

/** `qa [1: alpha]` — the node, and the branch it terminated in. */
function branchLabel(output: RunOutput): string {
  const branch = output.branch ?? []
  if (branch.length === 0) return output.node
  const keys = branch.map(
    (frame) =>
      `${String(frame.index)}${frame.key === undefined ? '' : `: ${formatValue(frame.key)}`}`,
  )
  return `${output.node} [${keys.join(' · ')}]`
}

/** A value as one line, cut where it stops being a preview. */
export function preview(value: unknown, limit: number = PREVIEW_LENGTH): string {
  const text = formatValue(value).replace(/\s+/g, ' ').trim()
  if (text === '') return DASH
  return text.length <= limit ? text : `${text.slice(0, limit)}…`
}

/**
 * The OUTPUTS list, or nothing at all.
 *
 * 10 §Panes shows it "when a run had more than one terminal branch", and
 * a run with one terminal task has its value in the run's own output
 * rather than in a list of one (04 §Routing edge cases). So one entry —
 * the linear case, and the fan-out closed by a join — draws no section.
 */
export function outputLines(outputs: readonly RunOutput[] | undefined): OutputLine[] {
  const list = outputs ?? []
  if (list.length < 2) return []
  return list.map((output) => ({
    taskId: output.task_id,
    node: branchLabel(output),
    preview: preview(output.value),
  }))
}

/**
 * The run list's filters, without a DOM: which columns filter and how,
 * whether a run passes, and what a column's popover offers.
 *
 * The column headers are the filter (D275). Each filterable column is
 * one of three kinds, chosen by what the column holds:
 *
 * - `text` — RUN and TITLE: free text, `contains`, case-folded.
 * - `choice` — WORKFLOW, STATUS and NODE: a closed set, `any of`.
 *   WORKFLOW offers the workflows there are runs of; STATUS offers the
 *   six statuses of 03 whether or not a run is in one, because the set
 *   is the enum's and not the data's; NODE offers the nodes runs are in
 *   now, since there is no one graph to take a node list from.
 * - `date` — AGE: `created between`, as a rolling window (`last 1h`) or
 *   a fixed range of two local datetimes.
 *
 * WORKFLOW's choices are also the workflow library's marks
 * (`overlays/Library.tsx`): both write the same field, so the funnel
 * and the library cannot disagree.
 *
 * The counts a popover shows are *faceted*: every other column's filter
 * applied, this column's own left out — "how many would I get if I
 * picked this?" — which is the only count that is not misleading once
 * two columns filter at once.
 */
import type { RunStatus, RunSummary } from '../../api/gen/types.gen'
import { EMPTY_RUN_FILTER, NO_NODE_FILTER, type RunFilter } from '../../store/ui'

/** A filterable column's key. */
export type FilterKey = 'id' | 'workflow' | 'title' | 'status' | 'node' | 'age'

/** How a column filters. */
export type FilterKind = 'text' | 'choice' | 'date'

/** One column, as the header draws it and the filter reads it. */
export type FilterColumn = {
  key: FilterKey
  /** The heading, which is also the popover's title. */
  label: string
  kind: FilterKind
}

/** The six columns, in grid order. */
export const COLUMNS: readonly FilterColumn[] = [
  { key: 'id', label: 'RUN', kind: 'text' },
  { key: 'workflow', label: 'WORKFLOW', kind: 'choice' },
  { key: 'title', label: 'TITLE', kind: 'text' },
  { key: 'status', label: 'STATUS', kind: 'choice' },
  { key: 'node', label: 'NODE', kind: 'choice' },
  { key: 'age', label: 'AGE', kind: 'date' },
]

/** The popover's second word for each kind: how the column matches. */
export const KIND_MODE: Record<FilterKind, string> = {
  text: 'contains',
  choice: 'any of',
  date: 'created between',
}

/** A text column's placeholder: what the operator might type. */
export const TEXT_PLACEHOLDER: Partial<Record<FilterKey, string>> = {
  id: 'e.g. 01k5',
  title: 'e.g. permission',
}

/** The run statuses of 03, in lifecycle order: the STATUS choices. */
export const RUN_STATUSES: readonly RunStatus[] = [
  'queued',
  'running',
  'paused',
  'completed',
  'failed',
  'cancelled',
]

/** What the NODE choice for a run in no node reads as. */
export const NO_NODE_LABEL = '(none)'

const MINUTE_MS = 60_000
const HOUR_MS = 60 * MINUTE_MS
const DAY_MS = 24 * HOUR_MS

/** The AGE presets: a label and the window it keeps. */
export const AGE_PRESETS: readonly { label: string; ms: number }[] = [
  { label: 'last 1h', ms: HOUR_MS },
  { label: 'last 24h', ms: DAY_MS },
  { label: 'last 7d', ms: 7 * DAY_MS },
  { label: 'last 30d', ms: 30 * DAY_MS },
]

/**
 * A `datetime-local` value as epoch milliseconds, or `null` when it is
 * empty or does not parse.
 *
 * `Date.parse` reads a date-time with no offset as local time, which is
 * what the input means by it.
 */
export function parseLocal(value: string): number | null {
  if (value === '') return null
  const ms = Date.parse(value)
  return Number.isNaN(ms) ? null : ms
}

/** Epoch milliseconds as a `datetime-local` value, to the minute. */
export function toLocalInput(ms: number): string {
  const date = new Date(ms)
  const pad = (n: number) => String(n).padStart(2, '0')
  return (
    `${String(date.getFullYear())}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}`
  )
}

/** Whether a column's filter narrows anything. */
export function columnActive(filter: RunFilter, key: FilterKey): boolean {
  switch (key) {
    case 'id':
      return filter.id.trim() !== ''
    case 'title':
      return filter.title.trim() !== ''
    case 'workflow':
      return filter.workflows.length > 0
    case 'status':
      return filter.statuses.length > 0
    case 'node':
      return filter.nodes.length > 0
    case 'age':
      return filter.within !== null || filter.after !== '' || filter.before !== ''
  }
}

/** How many columns filter: the footer's `× clear n filters`. */
export function activeCount(filter: RunFilter): number {
  return COLUMNS.filter((column) => columnActive(filter, column.key)).length
}

/** The patch that stops one column filtering. */
export function clearColumn(key: FilterKey): Partial<RunFilter> {
  switch (key) {
    case 'id':
      return { id: '' }
    case 'title':
      return { title: '' }
    case 'workflow':
      return { workflows: [] }
    case 'status':
      return { statuses: [] }
    case 'node':
      return { nodes: [] }
    case 'age':
      return {
        within: EMPTY_RUN_FILTER.within,
        after: EMPTY_RUN_FILTER.after,
        before: EMPTY_RUN_FILTER.before,
      }
  }
}

/** The nodes a run is in, or {@link NO_NODE_FILTER} when it is in none. */
export function runNodes(run: RunSummary): string[] {
  const nodes = run.current_nodes ?? []
  return nodes.length === 0 ? [NO_NODE_FILTER] : nodes
}

function contains(haystack: string, needle: string): boolean {
  const folded = needle.trim().toLowerCase()
  return folded === '' || haystack.toLowerCase().includes(folded)
}

/**
 * Whether `run` passes the AGE filter at `now`.
 *
 * A run whose `created` does not parse passes only when AGE is off: its
 * age is unknown, and an unknown is not inside any window (02 §Real data
 * only). `before` names a minute, and the whole of that minute is in
 * range — `TO 14:05` keeps a run created at 14:05:40.
 */
function passesAge(run: RunSummary, filter: RunFilter, now: number): boolean {
  if (!columnActive(filter, 'age')) return true
  const created = Date.parse(run.created)
  if (Number.isNaN(created)) return false
  if (filter.within !== null && created < now - filter.within) return false
  const after = parseLocal(filter.after)
  if (after !== null && created < after) return false
  const before = parseLocal(filter.before)
  if (before !== null && created >= before + MINUTE_MS) return false
  return true
}

/**
 * Whether `run` passes every column's filter but `except`'s.
 *
 * `except` is how a popover counts its own column's choices (faceting);
 * the list itself leaves it out.
 */
export function passes(
  run: RunSummary,
  filter: RunFilter,
  now: number,
  except?: FilterKey,
): boolean {
  if (except !== 'id' && !contains(run.id, filter.id)) return false
  if (except !== 'title' && !contains(run.title, filter.title)) return false
  if (
    except !== 'workflow' &&
    filter.workflows.length > 0 &&
    !filter.workflows.includes(run.workflow)
  ) {
    return false
  }
  if (
    except !== 'status' &&
    filter.statuses.length > 0 &&
    !filter.statuses.includes(run.status)
  ) {
    return false
  }
  if (
    except !== 'node' &&
    filter.nodes.length > 0 &&
    !runNodes(run).some((node) => filter.nodes.includes(node))
  ) {
    return false
  }
  if (except !== 'age' && !passesAge(run, filter, now)) return false
  return true
}

/** One choice in a STATUS or NODE popover. */
export type ChoiceOption = {
  value: string
  label: string
  /** Runs that would show with this choice on and the column's others off. */
  count: number
  on: boolean
}

/**
 * The choices a `choice` column offers, with their faceted counts.
 *
 * NODE's are the nodes the runs are in, by name, with `(none)` last: a
 * node no run is in would filter to nothing, and the `(none)` row is
 * about the absence of the others. A node the filter holds but no run
 * is in any more stays listed, so it can still be turned off.
 */
export function choiceOptions(
  key: 'workflow' | 'status' | 'node',
  runs: readonly RunSummary[],
  filter: RunFilter,
  now: number,
): ChoiceOption[] {
  const facet = runs.filter((run) => passes(run, filter, now, key))

  if (key === 'status') {
    return RUN_STATUSES.map((status) => ({
      value: status,
      label: status,
      count: facet.filter((run) => run.status === status).length,
      on: filter.statuses.includes(status),
    }))
  }

  if (key === 'workflow') {
    const names = new Set<string>(filter.workflows)
    for (const run of runs) names.add(run.workflow)
    return [...names]
      .sort((a, b) => a.localeCompare(b))
      .map((workflow) => ({
        value: workflow,
        label: workflow,
        count: facet.filter((run) => run.workflow === workflow).length,
        on: filter.workflows.includes(workflow),
      }))
  }

  const named = new Set<string>(filter.nodes)
  for (const run of runs) for (const node of runNodes(run)) named.add(node)
  const values = [...named].sort((a, b) =>
    a === NO_NODE_FILTER ? 1 : b === NO_NODE_FILTER ? -1 : a.localeCompare(b),
  )
  return values.map((node) => ({
    value: node,
    label: node === NO_NODE_FILTER ? NO_NODE_LABEL : node,
    count: facet.filter((run) => runNodes(run).includes(node)).length,
    on: filter.nodes.includes(node),
  }))
}

/**
 * How many of `runs` there are of each workflow with every filter but
 * WORKFLOW applied: the library's per-row counts.
 */
export function workflowCounts(
  runs: readonly RunSummary[],
  filter: RunFilter,
  now: number,
): Map<string, number> {
  const counts = new Map<string, number>()
  for (const run of runs) {
    if (!passes(run, filter, now, 'workflow')) continue
    counts.set(run.workflow, (counts.get(run.workflow) ?? 0) + 1)
  }
  return counts
}

/** Add `value` to `values`, or take it out if it is there. */
export function toggled<T>(values: readonly T[], value: T): T[] {
  return values.includes(value)
    ? values.filter((each) => each !== value)
    : [...values, value]
}

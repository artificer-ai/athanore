/**
 * How a plugin's values are read: printed, compared, and ordered.
 *
 * Separate from `./shape.ts` — which says what a kind's data *is* — and
 * from the components that draw it, because a component module that
 * exports a function is a module React Fast Refresh cannot update in
 * place (`.oxlintrc.json`, `react/only-export-components`).
 */

/**
 * One value of a plugin's data, as text.
 *
 * The generic renderers know what a value *is* and not what it *means*:
 * a number is printed as the number the source sent, with insignificant
 * decimals dropped so a duration of `12.300000000000001` seconds reads
 * as `12.3`, and nothing is rounded into a unit or scaled. The pane that
 * knows a field is TOKENS or DURATION formats it as such (T063a); this
 * one would only be guessing (01 §Real data only).
 *
 * `null` and `undefined` are the mock's `—`, which is what the overview
 * shows for a description a run does not have.
 */
export function formatValue(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'string') return value
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return String(value)
    return Number.isInteger(value) ? String(value) : String(Number(value.toFixed(2)))
  }
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  return JSON.stringify(value) ?? String(value)
}

/** A value's sort order within a column: numbers by size, text by text. */
export function compareValues(a: unknown, b: unknown): number {
  if (typeof a === 'number' && typeof b === 'number') return a - b
  if (a === null || a === undefined) return b === null || b === undefined ? 0 : 1
  if (b === null || b === undefined) return -1
  return formatValue(a).localeCompare(formatValue(b))
}

/** Which way a table column is sorted, or not (`./TablePane.tsx`). */
export type Direction = 'asc' | 'desc'
export type Sort = { key: string; direction: Direction } | null

/**
 * The next sort state for a click on `key`: none → ascending →
 * descending → none.
 *
 * Three states rather than two because a source's own row order is
 * information — the overview's NODES table is "the order the run entered
 * them" — and a third click is how it comes back.
 */
export function nextSort(sort: Sort, key: string): Sort {
  if (sort === null || sort.key !== key) return { key, direction: 'asc' }
  if (sort.direction === 'asc') return { key, direction: 'desc' }
  return null
}

/** `12:04:31` — the time of day, which is the log's first column (10). */
export function rowTime(ts: string): string {
  const at = new Date(ts)
  if (Number.isNaN(at.getTime())) return ts
  return at.toLocaleTimeString('en-GB', { hour12: false })
}

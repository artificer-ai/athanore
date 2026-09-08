/**
 * The data shapes of `docs/v1/09-plugins.md` §Panel kinds, and the
 * narrowing that decides whether a `source` answered with one.
 *
 * A panel's data arrives as `unknown`: it comes from a route the wire
 * contract does not describe (09 §Builtins are plugins — "a plugin route
 * is not part of the committed wire contract"), so there is no generated
 * type for it and the only honest starting point is that the server
 * answered with something. Each `as…` below is the whole of what the
 * table in 09 promises for one kind, and answers `null` for anything
 * else.
 *
 * `null` matters as much as the shape does. A plugin from a newer
 * version, or one whose route has a bug, must degrade to a card that
 * says so — never a white screen (09: "Unknown `kind` renders a
 * placeholder card, never a crash"; the same reasoning applies a
 * declared kind's data, which the renderer trusts no further).
 */

/** `table`: `{columns: [{key, label, kind?}], rows: [{…}]}`. */
export type TableColumn = { key: string; label?: string; kind?: string }
export type TableRow = Record<string, unknown>
export type TableData = { columns: TableColumn[]; rows: TableRow[] }

/** `log`: `[{ts, text, level?}]`, plus the `source` the builtin adds. */
export type LogRow = {
  ts: string
  text: string
  level?: string
  source?: string
  node?: string
}

/** `chart`: `{series: [{name, points: [[x, y]]}], kind: line|bar}`. */
export type ChartPoint = [number, number]
export type ChartSeries = { name: string; points: ChartPoint[] }
export type ChartData = { series: ChartSeries[]; kind: 'line' | 'bar' }

/** `dashboard`: `{note?, metrics: [{label, value}], table?}`. */
export type Metric = { label: string; value: unknown }
export type DashboardData = { note?: string; metrics: Metric[]; table?: TableData }

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function optionalString(value: unknown): string | undefined {
  return typeof value === 'string' ? value : undefined
}

/** `markdown`: a string, and the empty one is still a string. */
export function asMarkdown(data: unknown): string | null {
  return typeof data === 'string' ? data : null
}

/** `kv`: a plain object. Its values are formatted, not typed. */
export function asKv(data: unknown): Record<string, unknown> | null {
  return isRecord(data) ? data : null
}

function asColumn(value: unknown): TableColumn | null {
  if (!isRecord(value) || typeof value['key'] !== 'string') return null
  return {
    key: value['key'],
    ...(optionalString(value['label']) === undefined
      ? {}
      : { label: value['label'] as string }),
    ...(optionalString(value['kind']) === undefined
      ? {}
      : { kind: value['kind'] as string }),
  }
}

export function asTable(data: unknown): TableData | null {
  if (!isRecord(data)) return null
  const { columns, rows } = data
  if (!Array.isArray(columns) || !Array.isArray(rows)) return null
  const narrowed: TableColumn[] = []
  for (const column of columns) {
    const one = asColumn(column)
    if (one === null) return null
    narrowed.push(one)
  }
  if (!rows.every(isRecord)) return null
  return { columns: narrowed, rows: rows as TableRow[] }
}

export function asLog(data: unknown): LogRow[] | null {
  if (!Array.isArray(data)) return null
  const rows: LogRow[] = []
  for (const row of data) {
    if (!isRecord(row)) return null
    if (typeof row['ts'] !== 'string' || typeof row['text'] !== 'string') return null
    const level = optionalString(row['level'])
    const source = optionalString(row['source'])
    const node = optionalString(row['node'])
    rows.push({
      ts: row['ts'],
      text: row['text'],
      ...(level === undefined ? {} : { level }),
      ...(source === undefined ? {} : { source }),
      ...(node === undefined ? {} : { node }),
    })
  }
  return rows
}

function asPoint(value: unknown): ChartPoint | null {
  if (!Array.isArray(value) || value.length !== 2) return null
  const [x, y] = value
  if (typeof x !== 'number' || typeof y !== 'number') return null
  if (!Number.isFinite(x) || !Number.isFinite(y)) return null
  return [x, y]
}

export function asChart(data: unknown): ChartData | null {
  if (!isRecord(data) || !Array.isArray(data['series'])) return null
  const series: ChartSeries[] = []
  for (const entry of data['series']) {
    if (!isRecord(entry) || typeof entry['name'] !== 'string') return null
    if (!Array.isArray(entry['points'])) return null
    const points: ChartPoint[] = []
    for (const point of entry['points']) {
      const one = asPoint(point)
      if (one === null) return null
      points.push(one)
    }
    series.push({ name: entry['name'], points })
  }
  // `kind` is `line | bar`; anything else — including a kind a later
  // version adds — draws as a line rather than as nothing.
  return { series, kind: data['kind'] === 'bar' ? 'bar' : 'line' }
}

function asMetric(value: unknown): Metric | null {
  if (!isRecord(value) || typeof value['label'] !== 'string') return null
  return { label: value['label'], value: value['value'] }
}

export function asDashboard(data: unknown): DashboardData | null {
  if (!isRecord(data) || !Array.isArray(data['metrics'])) return null
  const metrics: Metric[] = []
  for (const metric of data['metrics']) {
    const one = asMetric(metric)
    if (one === null) return null
    metrics.push(one)
  }
  const table = data['table'] === undefined ? null : asTable(data['table'])
  if (data['table'] !== undefined && table === null) return null
  const note = optionalString(data['note'])
  return {
    metrics,
    ...(note === undefined ? {} : { note }),
    ...(table === null ? {} : { table }),
  }
}

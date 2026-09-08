/**
 * How a log row is read: its tone, its author, and which rows a pane
 * shows in what order (`docs/v1/10-frontend.md` §Panes item 2).
 *
 * Separate from the two components that draw rows — `./LogRows.tsx` and
 * `./Log.tsx` — for the reason `./format.ts` is separate: a module that
 * exports a function beside a component is one React Fast Refresh
 * cannot update in place (`.oxlintrc.json`, `react/only-export-
 * components`).
 *
 * Nothing here merges anything. The work log and the lifecycle events
 * are merged **server-side**, by `athanore/plugins/builtin/log.py`,
 * which is the one place that can tie-break two rows written in the same
 * transaction (an entry sorts before the event announcing it). What
 * {@link logLines} does is narrow that list to the node the operator
 * asked for and keep it in time order — a *stable* sort, so the
 * builtin's tie-break survives it and a plugin's own `log` panel, whose
 * route promises nothing about order, still draws oldest first.
 */
import type { LogRow } from './shape'

/**
 * 10 §Panes' three tones, as the classes that draw them.
 *
 * A tone, not a severity: 10 names exactly three for this pane, and the
 * builtin sets them from what wrote the line — `accent` for the stats
 * lines, `dim` for the engine and every lifecycle event, `default` for
 * what an agent or a person wrote.
 */
export const LOG_TONES: Record<string, string> = {
  accent: 'text-[var(--color-accent-300)]',
  dim: 'text-muted-foreground',
  default: 'text-[var(--color-neutral-300)]',
}

/**
 * The tone class of a row, falling back to the default for any other.
 *
 * Named for the log rather than for the tone because the app already
 * has a `toneClass`: the status colours of 10 §Status colours, which
 * these three are deliberately not (a log tone says who wrote a line,
 * not how a run is doing).
 */
export function logTone(level: string | undefined): string {
  return LOG_TONES[level ?? 'default'] ?? LOG_TONES['default'] ?? ''
}

/**
 * Who wrote a row, from the `node/author` the builtin's `source` is.
 *
 * A lifecycle event's source is `node/engine`, or bare `engine` when the
 * payload named no node, so the author is the last segment either way. A
 * plugin's row need not carry a source at all, and then nobody is named.
 */
export function logAuthor(row: LogRow): string | undefined {
  if (row.source === undefined) return undefined
  const slash = row.source.lastIndexOf('/')
  return slash === -1 ? row.source : row.source.slice(slash + 1)
}

/** The authors whose lines are prose (03 §LogEntry's `LogAuthor`). */
const PROSE_AUTHORS: ReadonlySet<string> = new Set(['agent', 'user'])

/**
 * Whether a row's text is markdown.
 *
 * 10 §Panes: "`agent` and `user` entries → default, with markdown". The
 * complement is what makes it worth stating — an engine line, and every
 * lifecycle sentence the builtin writes, is drawn as the text it is, so
 * a failure message carrying `#` or `*` cannot smuggle formatting into
 * the pane.
 */
export function isProse(row: LogRow): boolean {
  const author = logAuthor(row)
  return author !== undefined && PROSE_AUTHORS.has(author)
}

/** A row's instant, or `null` for a `ts` that is not one. */
function instant(ts: string): number | null {
  const at = Date.parse(ts)
  return Number.isNaN(at) ? null : at
}

/**
 * The rows a pane draws: `node`'s, if one was asked for, oldest first.
 *
 * `node` is the `?node=` filter the graph pane links into (10 §Panes:
 * "clicking a graph node opens this pane with `?node=` filtering to that
 * node's entries and events"). Rows carrying no node — a `run.created`,
 * whose payload names none — belong to no node and are filtered out with
 * the rest.
 *
 * The order is by time, and the sort is stable in both directions: rows
 * of the same instant keep the order their source gave them, and so does
 * a row whose `ts` is not a time at all, which is drawn where it arrived
 * rather than swept to one end.
 */
export function logLines(
  rows: readonly LogRow[],
  node?: string | undefined,
): LogRow[] {
  const kept = node === undefined ? [...rows] : rows.filter((row) => row.node === node)
  return kept
    .map((row, index) => ({ row, index, at: instant(row.ts) }))
    .sort((a, b) => {
      if (a.at === null || b.at === null) return a.index - b.index
      return a.at - b.at || a.index - b.index
    })
    .map((entry) => entry.row)
}

/**
 * Whether the log is still being written to, which is what the header's
 * `● tailing` / `○ complete` says (10 §Panes, and the mock's own
 * `tailLabel`).
 *
 * It is a fact about the *run* rather than about the scroller: a run
 * that is running is producing lines, and one in any other status has
 * produced all it is going to until something starts it again. A run
 * whose status has not arrived yet is not claimed to be live.
 */
export function isTailing(status: string | undefined): boolean {
  return status === 'running'
}

/**
 * What went wrong when a note could not be appended.
 *
 * The generated client throws the parsed error body — `{error, code}`,
 * the API's one error shape (08 §Conventions) — rather than an `Error`,
 * so both are read here and neither is assumed.
 */
export function appendError(error: unknown): string {
  if (typeof error === 'object' && error !== null) {
    const message = (error as { error?: unknown }).error
    if (typeof message === 'string' && message !== '') return message
    if (error instanceof Error && error.message !== '') return error.message
  }
  if (typeof error === 'string' && error.trim() !== '') return error
  return 'the note was not appended'
}

/**
 * What the task drawer says about one attempt, minus the drawing of it.
 *
 * A module of its own for the reason `./pickers.ts` and `./newRun.ts`
 * are: a file that exports a component and a function is one React Fast
 * Refresh cannot update in place (`.oxlintrc.json`,
 * `react/only-export-components`), and every rule below is worth testing
 * without a DOM.
 *
 * **Lineage is a sentence, not a JSON blob.** `tasks.lineage` is
 * `{reason, from?}` with one extra key on a join (`arrivals`), and its
 * seven reasons are the seven ways an attempt comes to exist: `start`,
 * `transition`, `retry` (the engine's own) and `join`, plus the three an
 * operator caused — `manual_retry`, `move` and `rerun`. The drawer is
 * where "why is there a second attempt of this node" gets answered, so
 * each is written out. A reason this build has never heard of is printed
 * under its own name rather than dropped (01 §Real data only), and the
 * parent it names is a task id the drawer can open, which is what makes
 * a chain of attempts walkable.
 *
 * **Set-status offers all three targets.** 04 gives `set_status(task,
 * ready|cancelled|dead_letter)` no precondition at all, and the drawer
 * is the surface where an operator acts on *this* attempt deliberately —
 * unlike the `x` picker, which is a convenience list and therefore
 * narrowed to what is still going. Only the status the attempt already
 * has is dropped, because writing a status onto itself is not an
 * operation (D175).
 */
import type {
  AthanoreApiSchemasTasksBranchFrame,
  SetStatus,
  TaskStatus,
} from '../api/gen/types.gen'
import { PENDING } from './pickers'

/** What each of the drawer's calls says when it was refused in silence. */
export const TASK_FALLBACKS = {
  retry: 'the attempt was not retried',
  move: 'the task was not moved',
  status: 'the status was not set',
} as const

/**
 * A status `set_status` accepts, which is a strict subset of the seven
 * an attempt can be in: the body of `POST /api/tasks/{id}/status` is a
 * closed union of three (08 §Tasks), and reading it off the generated
 * type is what stops this list drifting from the contract.
 */
export type SettableStatus = SetStatus['status']

/** The three targets of `set_status` (08 §Tasks, 04 §Operator operations). */
export const STATUS_TARGETS: readonly SettableStatus[] = [
  'ready',
  'cancelled',
  'dead_letter',
]

/**
 * The `lineage.reason` values the engine writes, each in two forms: the
 * phrase that runs into the parent's id, and the sentence for a row that
 * recorded no parent.
 *
 * Seven, and they are all of them: `start`, `transition` and `retry`
 * come from `athanore/engine/runner.py` and the join repo, and
 * `manual_retry`, `move` and `rerun` from `athanore/engine/ops.py`.
 * `set_status` is a *cancellation* reason on `task.cancelled`, not a
 * lineage: it moves an attempt rather than enqueueing one, so no row
 * ever carries it.
 */
const REASONS: Record<string, { from: string; alone: string }> = {
  start: { from: 'the run’s first attempt, after', alone: 'the run’s first attempt' },
  transition: {
    from: 'enqueued by a transition from',
    alone: 'enqueued by a transition',
  },
  retry: { from: 'the engine’s retry of', alone: 'the engine’s own retry' },
  join: {
    from: 'the join closing the fan-out at',
    alone: 'the join closing a fan-out',
  },
  manual_retry: { from: 'an operator’s retry of', alone: 'an operator’s retry' },
  move: { from: 'moved here from', alone: 'moved here by an operator' },
  rerun: {
    from: 'an operator’s rerun of this node, last run by',
    alone: 'an operator’s rerun of this node',
  },
}

/** What the LINEAGE row says, and the attempts it points at. */
export type LineageLine = {
  /** The sentence, with the parent's id already in it when there is one. */
  text: string
  /** `lineage.from`: the attempt this one came out of, when it named one. */
  parent: number | undefined
  /** A join's arriving attempts, in the order the engine recorded them. */
  arrivals: number[]
}

/** An integer that is a task id, or `undefined` for anything else. */
function taskId(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isInteger(value) && value > 0
    ? value
    : undefined
}

/**
 * `tasks.lineage` read as a line of English.
 *
 * A lineage the server did not send at all — the column is nullable —
 * says so rather than inventing a reason for the row.
 */
export function lineageLine(
  lineage: Record<string, unknown> | null | undefined,
): LineageLine {
  if (lineage === null || lineage === undefined) {
    return { text: 'this attempt records no lineage', parent: undefined, arrivals: [] }
  }

  const reason = lineage['reason']
  const parent = taskId(lineage['from'])
  const arrivals = Array.isArray(lineage['arrivals'])
    ? (lineage['arrivals'] as unknown[])
        .map(taskId)
        .filter((id): id is number => id !== undefined)
    : []

  const name = typeof reason === 'string' && reason !== '' ? reason : 'unknown'
  const phrases = REASONS[name] ?? {
    from: `enqueued for “${name}”, from`,
    alone: `enqueued for “${name}”`,
  }

  return {
    text:
      parent === undefined ? phrases.alone : `${phrases.from} task #${String(parent)}`,
    parent,
    arrivals,
  }
}

/** `branch 2 of 3 · beta · from task #26` — one line per frame, outermost first. */
export function branchLines(
  branch: readonly AthanoreApiSchemasTasksBranchFrame[] | undefined,
  format: (value: unknown) => string,
): string[] {
  return (branch ?? []).map((frame) => {
    const key = frame.key === undefined || frame.key === null ? undefined : format(frame.key)
    return [
      `branch ${String(frame.index + 1)} of ${String(frame.count)}`,
      key,
      `from task #${String(frame.fanout)}`,
    ]
      .filter((part) => part !== undefined)
      .join(' · ')
  })
}

/** Whether `retry` would be accepted: 04 refuses an attempt still going. */
export function canRetry(status: TaskStatus): boolean {
  return !PENDING.includes(status)
}

/** The set-status targets worth offering for an attempt in `status`. */
export function statusTargets(status: TaskStatus): SettableStatus[] {
  return STATUS_TARGETS.filter((target) => target !== status)
}

/** A `TaskStatus` as the buttons label it: `dead letter`, not `dead_letter`. */
export function statusLabel(status: string): string {
  return status.replace(/_/g, ' ')
}

/**
 * A value as the drawer prints it: indented JSON, or `null` for the one
 * the wire always sends when there is nothing.
 *
 * `undefined` cannot survive JSON, so it only reaches here from a field
 * a server one version behind never sent; it prints as `null` too,
 * because that is what the wire would have carried.
 */
export function jsonBlock(value: unknown): string {
  return JSON.stringify(value ?? null, null, 2) ?? 'null'
}

/** A timestamp as the drawer prints it: the whole thing, in local time. */
export function stamp(ts: string | null | undefined): string | undefined {
  if (ts === null || ts === undefined || ts === '') return undefined
  const at = new Date(ts)
  if (Number.isNaN(at.getTime())) return ts
  return at.toLocaleString('en-GB', { hour12: false })
}

/** `6 · declared` / `6 · default` — the priority, and where it came from. */
export function priorityLine(priority: number, explicit: boolean): string {
  return `${String(priority)} · ${explicit ? 'declared on the node' : 'the workflow’s default'}`
}

/** The stats entry as rows, in the order the adapter wrote them (05 §Stats). */
export function statsRows(
  stats: Record<string, unknown> | null | undefined,
  format: (value: unknown) => string,
): Array<[string, string]> {
  if (stats === null || stats === undefined) return []
  return Object.entries(stats).map(([key, value]) => [key, format(value)])
}

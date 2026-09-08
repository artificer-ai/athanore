/**
 * The status colours of `docs/v1/10-frontend.md` §Status colours, as the
 * run list uses them.
 *
 * The table maps a *state* to a token and a treatment, and the run
 * statuses of 03 are six of the states it names. One reading is worth
 * spelling out: a run with open requests is waiting on a person, so 10
 * §Attention says "its status pill gains the gate colour" — the gate row
 * of the table, whose treatment is plain. The tone therefore carries the
 * whole treatment, pulse included, and a run that is `running` but
 * parked on a request does not pulse: nothing is in progress.
 *
 * The classes are written out rather than built from the tone, because
 * Tailwind generates a utility only where it can see its name in the
 * source (`src/styles/theme.css` declares them; a template literal would
 * leave every one of them out of the bundle).
 */
import type { RunStatus } from '../../api/gen/types.gen'

/** A row of 10 §Status colours. */
export type StatusTone = 'ok' | 'active' | 'gate' | 'queued' | 'fail' | 'muted' | 'paused'

/** Every run status of 03, against the state it is in that table. */
const TONES: Record<RunStatus, StatusTone> = {
  queued: 'queued',
  running: 'active',
  paused: 'paused',
  completed: 'ok',
  failed: 'fail',
  cancelled: 'muted',
}

/** The colour utility for each tone (`text-status-*` from T057). */
const TONE_CLASSES: Record<StatusTone, string> = {
  ok: 'text-status-ok',
  active: 'text-status-active',
  gate: 'text-status-gate',
  queued: 'text-status-queued',
  fail: 'text-status-fail',
  muted: 'text-status-muted',
  paused: 'text-status-paused',
}

/**
 * The tone a run's status pill carries.
 *
 * `pendingRequests` is the run's unanswered, non-stale requests: while
 * there is one, the run is at a gate whatever its status says.
 */
export function statusTone(status: RunStatus, pendingRequests: number): StatusTone {
  return pendingRequests > 0 ? 'gate' : TONES[status]
}

/** The colour utility for a tone. */
export function toneClass(tone: StatusTone): string {
  return TONE_CLASSES[tone]
}

/** Whether a tone pulses: `active` alone (10 §Status colours). */
export function tonePulses(tone: StatusTone): boolean {
  return tone === 'active'
}

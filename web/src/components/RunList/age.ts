/**
 * The AGE column's clock (`docs/v1/10-frontend.md` §Layout, §Panes).
 *
 * The mock writes ages as `4m`, `55m`, `1.0h`, `15.3h`, `2.6d`, `16.7d`:
 * one unit, chosen by magnitude, with a decimal once the unit is coarse
 * enough for one to matter. Below a minute it counts seconds, which the
 * mock has no example of because its rows are all older than that and a
 * live run's first row is not.
 *
 * `created` is the ISO timestamp the API sends. A value that does not
 * parse is not guessed at: it renders as {@link UNKNOWN_AGE}, because 02
 * §Real data only says an unknown is omitted rather than zero-filled.
 */

/** What an age that cannot be computed reads as. */
export const UNKNOWN_AGE = '—'

const SECOND_MS = 1000
const MINUTE_MS = 60 * SECOND_MS
const HOUR_MS = 60 * MINUTE_MS
const DAY_MS = 24 * HOUR_MS

/**
 * An elapsed span, in the mock's shorthand.
 *
 * A negative span is reported as `0s` rather than with a minus sign: a
 * clock a second or two ahead of the server's is ordinary, and a row
 * reading `-1s` would say something about the data that is not true.
 *
 * The overview pane's AGE field is the same shorthand over a span the
 * server already measured in seconds (10 §Panes), which is why the
 * formatting lives here rather than inside {@link humaniseAge}: one
 * definition of `15.8d`, two callers.
 */
export function humaniseElapsed(elapsedMs: number): string {
  const elapsed = Math.max(0, elapsedMs)
  if (elapsed < MINUTE_MS) return `${Math.floor(elapsed / SECOND_MS)}s`
  if (elapsed < HOUR_MS) return `${Math.floor(elapsed / MINUTE_MS)}m`
  if (elapsed < DAY_MS) return `${(elapsed / HOUR_MS).toFixed(1)}h`
  return `${(elapsed / DAY_MS).toFixed(1)}d`
}

/** `now − created`, in the mock's shorthand. */
export function humaniseAge(created: string, now: number = Date.now()): string {
  const started = Date.parse(created)
  if (Number.isNaN(started)) return UNKNOWN_AGE

  return humaniseElapsed(now - started)
}

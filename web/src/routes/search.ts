/**
 * The app's search parameters: every piece of UI state worth sharing.
 *
 * The whole SPA is one route, so a view is linkable only if the things
 * that make it that view live in the query string: which run is
 * selected, which pane is showing, which overlay is open, and which task
 * the overlay is about. Widths and preferences are personal and belong
 * to `usePrefs` instead.
 *
 * Validation **drops** what it does not recognise rather than throwing. A
 * stale bookmark carrying `?overlay=crt` from an older build must open the
 * app, not white-screen it, so every field is parsed independently and a
 * field that fails is simply absent from the result.
 */

/**
 * The overlays of 10 §Overlays, in the order that section lists them,
 * plus the two it does not list: `delete` is the confirm 10 §Keyboard
 * asks `D` to open (T066e), and `action` is where a plugin action the
 * palette listed is filled in and run (T070). Both are overlays like the
 * rest, because it is `?overlay=` that says an overlay is up.
 */
export const OVERLAYS = [
  'palette',
  'new',
  'library',
  'edit',
  'keys',
  'task',
  'delete',
  'pick-retry',
  'pick-move',
  'pick-cancel',
  'pick-rerun',
  'action',
] as const

export type Overlay = (typeof OVERLAYS)[number]

/**
 * The validated search of route `/`.
 *
 * - `run` — the selected run's ULID.
 * - `pane` — the zero-based index into the pane cycle. The pane host
 *   clamps it to the selected run's pane count (T062); here it only has
 *   to be an index.
 * - `overlay` — the open overlay, one of {@link OVERLAYS}.
 * - `task` — the task an overlay is about; task ids are positive
 *   integers.
 * - `node` — the node the event log is filtered to. The graph pane
 *   writes it ("clicking a graph node opens this pane with `?node=`
 *   filtering to that node's entries and events", 10 §Panes), which is
 *   what makes a filtered log a link somebody can send.
 * - `action` — `<workflow>:<name>`, the plugin action the `action`
 *   overlay is about. Opaque here for the same reason `run` and `node`
 *   are: which actions exist is the installed workflows' business, and
 *   the overlay says so when the manifest carries none by that name.
 * - `global` — the narrow global screen's pane index: the zero-based
 *   index into the `global` cycle, present exactly while that screen is
 *   up. Read only while `run` is unset — the global screen sits beside
 *   the list, never over a run (D218) — and inert beside `run`, as it
 *   is at `md` and above, where the detail is the global panes
 *   whenever nothing is selected (21 §Narrow layout, D216). Kept
 *   whatever `run` is, for the reason `listCollapsed` is kept below
 *   the breakpoint: dropping it would make a phone's link opened at
 *   another width forget where it was. It is not `pane` reused, so a
 *   visit to the global panes leaves the operator's pane index where
 *   it was.
 */
export type AppSearch = {
  run?: string
  pane?: number
  overlay?: Overlay
  task?: number
  node?: string
  action?: string
  global?: number
}

const OVERLAY_SET: ReadonlySet<string> = new Set(OVERLAYS)

function isOverlay(value: unknown): value is Overlay {
  return typeof value === 'string' && OVERLAY_SET.has(value)
}

/** A non-empty string, trimmed of nothing: run ids are opaque. */
function asId(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() !== '' ? value : undefined
}

/**
 * An integer at or above `min`. The router parses `?pane=2` to a number
 * already; a hand-typed `?pane=two` arrives as a string and fails here.
 */
function asInteger(value: unknown, min: number): number | undefined {
  const n =
    typeof value === 'number'
      ? value
      : typeof value === 'string' && value.trim() !== ''
        ? Number(value)
        : Number.NaN
  return Number.isInteger(n) && n >= min ? n : undefined
}

/**
 * Parse the raw search object into {@link AppSearch}, dropping anything
 * that does not validate. Never throws.
 */
export function validateAppSearch(search: Record<string, unknown>): AppSearch {
  const run = asId(search['run'])
  const pane = asInteger(search['pane'], 0)
  const overlay = search['overlay']
  const task = asInteger(search['task'], 1)
  // A node name is a workflow's, so it is opaque here for the same
  // reason a run id is: this build cannot know which names the selected
  // run's graph has, and the log pane draws no rows for one it has not.
  const node = asId(search['node'])
  const action = asId(search['action'])
  const global = asInteger(search['global'], 0)

  return {
    ...(run === undefined ? {} : { run }),
    ...(pane === undefined ? {} : { pane }),
    ...(isOverlay(overlay) ? { overlay } : {}),
    ...(task === undefined ? {} : { task }),
    ...(node === undefined ? {} : { node }),
    ...(action === undefined ? {} : { action }),
    ...(global === undefined ? {} : { global }),
  }
}

/**
 * The command palette's catalogue: every operator action the app can
 * perform and every overlay it can open, each with the key that also
 * performs it.
 *
 * The table is the design mock's `COMMANDS` with the corrections 10
 * makes to it — `edit run` is title and description only, because the
 * mock's priority slider became the new-run overlay's POSITION (D34) —
 * and with the two rows the mock's palette omits from its own key map:
 * `toggle list` and `keys`.
 *
 * **The palette lists what the app can do, and nothing else.** It is a
 * menu, not a place features are built: a command belongs here once the
 * task that implements it has landed, so an operator who cannot find
 * something here cannot do it at all. The three rows T066a left out —
 * `pause / resume run` (`p`), `cancel run` (`c`) and `delete run` (`D`)
 * — joined it with T066e, which is the task whose done condition is that
 * every operator op of 04 is reachable from the UI (D170, D175).
 *
 * **Six rows carry no key, and say so.** `reorder(run, direction)` is an
 * operator op of 04 that 10 §Keyboard has no binding for, and that
 * section is exhaustive — T067 binds exactly it — so the two rows that
 * move a run up and down the dispatch list print `—` in the key column
 * rather than advertising a key this app does not have (D175). The New
 * Run overlay's POSITION is the same op with `{index: 0}` (D57). The
 * four `font size: …` rows are keyless for the same reason: they are the
 * keyboard-first half of the header's chooser (D196), and 10 §Keyboard
 * binds no key to them either.
 *
 * Two shapes of command live here and they end the palette differently:
 *
 * - an **overlay** command replaces the palette with another overlay, by
 *   writing `?overlay=`, which is the one piece of state that says which
 *   overlay is up. There is nothing to close: the navigation that opens
 *   the next overlay closes this one.
 * - a **direct** command does something to the app and dismisses the
 *   palette itself, so it closes first and acts after.
 *
 * Rows the current selection cannot support are listed and disabled
 * rather than hidden: a palette that grows and shrinks is no longer the
 * shortcut list it doubles as, and "retry task" with no run selected is
 * a command that exists and is not available, which is what a disabled
 * row says.
 */
import type { Overlay } from '../routes/search'
import { FONT_SIZES, type FontSize } from '../store/prefs'

/**
 * What the palette needs from the app to turn a command into an action.
 *
 * `close` and `openOverlay` are two different navigations and not one
 * with an argument: closing writes `?overlay=` away, opening writes the
 * next one, and a command that did both would race its own two writes.
 */
export type PaletteContext = {
  /** The selected run, or `undefined` when nothing is selected. */
  runId: string | undefined
  /** Show an overlay: `?overlay=<name>`. */
  openOverlay: (overlay: Overlay) => void
  /** Dismiss the palette: `?overlay=` away. */
  close: () => void
  /** `^r`: refetch everything this tab holds. */
  refresh: () => void
  /** `b`: collapse the run list to its rail, or bring it back. */
  toggleList: () => void
  /** `l`: show the log pane and put the caret in its composer. */
  appendLog: () => void
  /**
   * `p`: pause a running or queued run, resume a paused one.
   *
   * The status is the shell's to know — it holds `GET /api/runs` — so
   * the command asks for the toggle and does not name a direction. A
   * run in a terminal status is neither pausable nor resumable, which
   * is what {@link PaletteContext.canPauseResume} says.
   */
  pauseResume: () => void
  /** Whether `p` would do anything to the selected run right now. */
  canPauseResume: boolean
  /** `c`: cancel every attempt of the run. */
  cancelRun: () => void
  /** The palette's `move run up` / `move run down` (`reorder`, 04). */
  reorder: (direction: 'up' | 'down') => void
  /**
   * The UI type scale's base (21 §Type scale). The four rows are the
   * header chooser's keyboard-first twin, and write the same pref.
   */
  setFontSize: (fontSize: FontSize) => void
}

/** One row of the palette: `name · hint · key`, and what it does. */
export type PaletteAction = {
  /** Stable across renders and unique: cmdk keys its items by it. */
  id: string
  /** The left column, and what a query matches first. */
  name: string
  /** The middle column: what the command does, in a few words. */
  hint: string
  /** The right column: the shortcut, written as the footer writes it. */
  key: string
  /**
   * The heading this row sits under, or `null` for the app's own
   * commands, which the mock lists without one. Plugin actions arrive
   * grouped under `plugin: <title>` (T070).
   */
  group: string | null
  /** Listed, shown with its key, and not runnable in this state. */
  disabled: boolean
  /** Run it. Ends the palette, one of the two ways described above. */
  run: () => void
}

/**
 * The rows, in order, split into the runs that share a heading.
 *
 * Order is the catalogue's: a group is opened by the first row that
 * carries it and closed by the next row that does not, so a caller
 * decides both the sections and what is in them by the order it hands
 * the actions over.
 */
export function groupActions(
  actions: readonly PaletteAction[],
): Array<{ group: string | null; actions: PaletteAction[] }> {
  const sections: Array<{ group: string | null; actions: PaletteAction[] }> = []

  for (const action of actions) {
    const last = sections.at(-1)
    if (last !== undefined && last.group === action.group) {
      last.actions.push(action)
    } else {
      sections.push({ group: action.group, actions: [action] })
    }
  }

  return sections
}

/** The key column of a row that has no key (10 §Keyboard is exhaustive). */
export const KEYLESS = '—'

/** A catalogue entry, before a context turns it into a {@link PaletteAction}. */
type PaletteCommand = {
  id: string
  name: string
  hint: string
  key: string
  /** Whether the command is about the selected run. */
  needsRun: boolean
  /**
   * A second condition on top of the selection, for the one command
   * that has one. Absent means "a selected run is enough".
   */
  available?: (ctx: PaletteContext) => boolean
  perform: (ctx: PaletteContext) => void
}

/** An overlay command: the navigation that opens it is all it does. */
function opens(overlay: Overlay): (ctx: PaletteContext) => void {
  return (ctx) => {
    ctx.openOverlay(overlay)
  }
}

/**
 * The catalogue, in the mock's order, `append log` in the place the mock
 * puts it: the overlays as the mock lists them, then the commands the
 * shell performs itself, with `refresh` last where the mock leaves it.
 */
export const PALETTE_COMMANDS: readonly PaletteCommand[] = [
  {
    id: 'new-run',
    name: 'new run',
    hint: 'submit a run against a workflow',
    key: 'n',
    needsRun: false,
    perform: opens('new'),
  },
  {
    id: 'retry-task',
    name: 'retry task',
    hint: 'rerun the focused node',
    key: 't',
    needsRun: true,
    perform: opens('pick-retry'),
  },
  {
    id: 'move-task',
    name: 'move task',
    hint: 'send the run to another node',
    key: 'm',
    needsRun: true,
    perform: opens('pick-move'),
  },
  {
    id: 'cancel-task',
    name: 'cancel task',
    hint: 'stop the running node',
    key: 'x',
    needsRun: true,
    perform: opens('pick-cancel'),
  },
  {
    id: 'append-log',
    name: 'append log',
    hint: 'add a note to the run log',
    key: 'l',
    needsRun: true,
    perform: (ctx) => {
      ctx.close()
      ctx.appendLog()
    },
  },
  {
    id: 'rerun-node',
    name: 'rerun node',
    hint: 'replay from this node',
    key: 'r',
    needsRun: true,
    perform: opens('pick-rerun'),
  },
  {
    id: 'pause-resume-run',
    name: 'pause / resume run',
    hint: 'hold the orchestrator',
    key: 'p',
    needsRun: true,
    // The one command whose availability is not just "is a run
    // selected": 04 gives `pause` and `resume` preconditions that
    // between them cover every non-terminal run, so a terminal one is
    // listed and disabled rather than posting a 409 to find out.
    available: (ctx) => ctx.canPauseResume,
    perform: (ctx) => {
      ctx.close()
      ctx.pauseResume()
    },
  },
  {
    id: 'cancel-run',
    name: 'cancel run',
    hint: 'stop every queued node',
    key: 'c',
    needsRun: true,
    perform: (ctx) => {
      ctx.close()
      ctx.cancelRun()
    },
  },
  {
    id: 'delete-run',
    name: 'delete run',
    hint: 'remove the run and its logs',
    key: 'D',
    needsRun: true,
    perform: opens('delete'),
  },
  {
    id: 'move-run-up',
    name: 'move run up',
    hint: 'earlier in the dispatch list',
    key: KEYLESS,
    needsRun: true,
    perform: (ctx) => {
      ctx.close()
      ctx.reorder('up')
    },
  },
  {
    id: 'move-run-down',
    name: 'move run down',
    hint: 'later in the dispatch list',
    key: KEYLESS,
    needsRun: true,
    perform: (ctx) => {
      ctx.close()
      ctx.reorder('down')
    },
  },
  {
    id: 'edit-run',
    name: 'edit run',
    hint: 'change the title and description',
    key: 'e',
    needsRun: true,
    perform: opens('edit'),
  },
  {
    id: 'workflow-library',
    name: 'open workflow library',
    hint: 'python definitions',
    key: 'w',
    needsRun: false,
    perform: opens('library'),
  },
  {
    id: 'keys',
    name: 'keys',
    hint: 'the keyboard map, expanded',
    key: '?',
    needsRun: false,
    perform: opens('keys'),
  },
  {
    id: 'toggle-list',
    name: 'toggle list',
    hint: 'collapse the run list to its rail',
    key: 'b',
    needsRun: false,
    perform: (ctx) => {
      ctx.close()
      ctx.toggleList()
    },
  },
  // The header's chooser, as rows: 21 §Type scale asks for the four
  // steps here so the keyboard-first path exists too (D196). They are
  // about the browser and not the run, so none of them needs one.
  ...FONT_SIZES.map((step) => ({
    id: `font-size-${step}`,
    name: `font size: ${step}`,
    hint: 'the interface type scale',
    key: KEYLESS,
    needsRun: false,
    perform: (ctx: PaletteContext) => {
      ctx.close()
      ctx.setFontSize(step)
    },
  })),
  {
    id: 'refresh',
    name: 'refresh',
    hint: 'refetch from the daemon',
    key: '^r',
    needsRun: false,
    perform: (ctx) => {
      ctx.close()
      ctx.refresh()
    },
  },
]

/** Bind {@link PALETTE_COMMANDS} to one app state. */
export function buildPaletteActions(ctx: PaletteContext): PaletteAction[] {
  return PALETTE_COMMANDS.map((command) => {
    const disabled =
      (command.needsRun && ctx.runId === undefined) ||
      (command.available !== undefined && !command.available(ctx))

    return {
      id: command.id,
      name: command.name,
      hint: command.hint,
      key: command.key,
      group: null,
      disabled,
      // The palette does not run a disabled row and cmdk will not select
      // one, so this guard is the action's own: an action is a value the
      // keyboard map and the plugin host will hold too (T067, T070), and
      // "retry task" is not a thing to do with no run selected however
      // it was reached.
      run: () => {
        if (disabled) return
        command.perform(ctx)
      },
    }
  })
}

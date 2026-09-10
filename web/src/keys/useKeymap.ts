/**
 * `useKeymap` — the app's one `keydown` listener, and the table of
 * `docs/v1/10-frontend.md` §Keyboard behind it.
 *
 * That section is exhaustive and this hook binds exactly it: `↑`/`↓` or
 * `j`/`k` select — or move the focused run, while one is held — `←`/`→`
 * cycle panes, `1`–`9` jump, `⏎` focus run,
 * `tab` focus, `t` retry task, `m` move task, `x` cancel task, `l`
 * append log, `n` new run, `r` rerun node, `p` pause/resume, `c` cancel
 * run, `D` (shift) delete run, `e` edit run, `w` workflows, `b` toggle
 * list, `?` keys, `^p` palette, `^r` refresh, `esc` close, and — in the
 * request panel alone — `a` allow and `d` deny.
 *
 * **The commands are not written twice.** Fourteen of those keys are
 * rows of the palette's catalogue (`overlays/actions.ts`), which already
 * carries the keycap that runs each one, so the map dispatches on that
 * column rather than keeping a second list that could drift from it. The
 * keys left over are the ones the palette has no row for, because a
 * palette cannot open itself and a list cannot be scrolled from a
 * command: they arrive as handlers.
 *
 * **Scoping is the point.** A `d` typed into the header's `/` input must
 * not open the delete confirm, and neither must a `d` pressed inside an
 * overlay — which is the whole reason 10 moved delete off `d` and onto
 * `D` (D51). Three rules, in the order the mock applies them
 * (`docs/v1/design/Athanore.dc.html`):
 *
 * 1. `esc` closes whatever is up, from anywhere, including an input.
 * 2. A **chord** — `^p`, `^r` — is not typing and is not the overlay's,
 *    so it fires wherever the caret is. `alt` chords are nobody's here
 *    and are left alone.
 * 3. Every **plain** key is suppressed while the target is an input, a
 *    textarea, a select or a contenteditable, and while an overlay owns
 *    the keyboard (`./scope.ts`). "The target" is read off
 *    `composedPath()`, so a field inside a plugin pane's shadow root
 *    counts like any other (D210).
 *
 * `a` and `d` are plain keys with one more condition on top: the
 * keystroke has to have come from inside a request panel, which
 * registers them (`./scope.ts`). Outside one they do nothing at all —
 * they are not the app's keys, so they do not fall through to it.
 *
 * `tab` is deliberately **not** intercepted (D176): it is the browser's
 * own focus key, the two regions already follow it (`store/ui.ts`), and
 * taking it would leave a keyboard-only operator unable to reach the
 * header's filter, the pane bar or a request's buttons — which 10
 * §Accessibility and quality does not allow. The mock binds every other
 * key of the map and not this one. It is also how the detail pane is
 * reached: `⏎` used to send the keyboard there and now picks a run up
 * instead (D204 (1)).
 *
 * **A held run changes two keys and no others.** While `runFocused`,
 * `↑`/`↓` and `j`/`k` call `moveRun` rather than `select`; everything
 * else in the map does what it always does. Those four caps are not
 * scoped to the run list, exactly as `select` is not — the mode is
 * explicit and drawn on the row it is about — so they fire from
 * wherever the plain keys apply. `⏎` keeps the list scope it has always
 * had, because the list is where a run is picked up from, and `esc`
 * puts one down from anywhere, as `esc` always has.
 */
import { useEffect, useRef } from 'react'

// The leaf module and not the `panes` barrel: the barrel pulls in the
// renderers, and what is wanted here is the one constant the pane host
// already declares for this binding — how many panes a number key
// reaches — so that `1`–`9` is written down once.
import { JUMP_KEYS } from '../panes/usePanes'
import { answerKeysAt, keyboardOwned } from './scope'

/** The run list region, for the one binding that is scoped to it. */
export const LIST_REGION = '[data-region="list"]'

/** What a key runs: one row of the palette's catalogue, narrowed. */
export type KeymapAction = {
  /** The keycap, written as the footer and the palette write it. */
  key: string
  /** Whether this state can run it; a disabled row's key does nothing. */
  disabled: boolean
  /** Do it. */
  run: () => void
}

/** Everything the map needs that is not already a palette command. */
export type KeymapHandlers = {
  /** The catalogue, dispatched on its key column. */
  actions: readonly KeymapAction[]
  /** `↑`/`↓`/`j`/`k`: move the selection by one row, clamped. */
  select: (delta: number) => void
  /** `←`/`→`: the pane cycle, wrapping. */
  cyclePane: (delta: number) => void
  /** `1`–`9`: the pane at this zero-based index, if there is one. */
  jumpPane: (index: number) => void
  /**
   * Whether a run is held, which is what `↑`/`↓` and `j`/`k` dispatch
   * on. The shell decides it; the map only reads it.
   */
  runFocused: boolean
  /** `⏎`: pick the selected run up, or put the held one down. */
  toggleRunFocus: () => void
  /** `↑`/`↓`/`j`/`k`, while a run is held: move it one place. */
  moveRun: (delta: -1 | 1) => void
  /** `^p`: the command palette. */
  openPalette: () => void
  /** `esc`: close whatever is open. */
  close: () => void
}

/**
 * What a keystroke belongs to rather than to the app.
 *
 * The three editable values of `contenteditable` and not the bare
 * attribute: `contenteditable="false"` is markup inside an editor that
 * is deliberately *not* editable, and a key pressed there is the app's
 * like any other. `isContentEditable` says the same thing where it is
 * implemented and is checked first; jsdom implements neither
 * contenteditable nor that property, so the attribute is what the tests
 * — and any browser reading inherited editability — actually see.
 */
const TYPING =
  'input, textarea, select, [contenteditable=""], [contenteditable="true"], [contenteditable="plaintext-only"]'

/**
 * Whether the operator is typing, in which case the map is off.
 *
 * Takes the **event**, not its target, because of the shadow DOM. An
 * event that crosses a shadow boundary is *retargeted*: `event.target`
 * becomes the host element, so a keystroke in an `<input>` inside a
 * plugin's `custom` pane arrives looking like one aimed at
 * `<athanore-cron>` — an element that matches nothing in {@link TYPING}
 * and has no input to `closest` its way up to. Typing `1` into a field
 * therefore jumped to pane 1 (D210).
 *
 * `composedPath()` is the path *before* retargeting, so the real
 * innermost node is its first entry and the walk sees the field. The
 * loop stops at the host of any closed root, which is all any caller can
 * know: a plugin that closes its shadow root has opted out of the app
 * being able to tell, and the map stays on over it.
 */
export function isTyping(event: Event): boolean {
  for (const node of event.composedPath()) {
    if (!(node instanceof Element)) continue
    if (node instanceof HTMLElement && node.isContentEditable) return true
    // `matches` per node rather than one `closest`: the path already
    // *is* the ancestor chain, through every shadow boundary the event
    // crossed, which is the part `closest` cannot walk.
    if (node.matches(TYPING)) return true
  }
  return false
}

/**
 * The keycap this event is, in the notation the catalogue uses, or
 * `null` when it is not one this app writes down.
 *
 * `^p` rather than `Ctrl+p` because that is how 10 §Keyboard, the footer
 * strip and the palette's key column all write it, and the point of one
 * notation is that the table is dispatched on directly.
 *
 * This is the *dispatch* column — `event.key` — and what the footer
 * strip, the `?` overlay and the palette *draw* is `capLabel` of it
 * (`lib/keys.ts`), so `D` is bound and `⇧D` is shown without a second
 * table to keep in step (D207).
 */
export function capOf(event: KeyboardEvent): string | null {
  if (event.altKey) return null
  if (event.ctrlKey || event.metaKey) {
    return event.key.length === 1 ? `^${event.key.toLowerCase()}` : null
  }
  return event.key
}

/** The catalogue row this cap runs, if any. */
function actionFor(
  actions: readonly KeymapAction[],
  cap: string | null,
): KeymapAction | undefined {
  if (cap === null) return undefined
  return actions.find((action) => action.key === cap)
}

/**
 * Whether `⏎` is the run list's, which is the only place it is bound.
 *
 * "`⏎` focus run" is what the run list's own footer strip advertises,
 * and that is the scope: from a run row, from the list's chrome, and
 * from the page itself, where nothing has claimed the keyboard and the
 * list is the region a fresh page starts on (`store/ui.ts`). Enter
 * anywhere else belongs to whatever has focus — the header's `＋ new
 * run`, a composer, a pane's own control.
 *
 * It **does** cancel the keystroke, run row or not. A row is a
 * `<button>`, so an uncancelled Enter would also click it, and "does
 * Enter select?" would depend on which element happened to hold focus.
 * `↑`/`↓` and `j`/`k` are what select a run, and they write `?run=`
 * directly; the row is an `option` in a `listbox`, where selection
 * follows the cursor and Enter is not the activation key. So Enter does
 * one thing here, and does it from everywhere in the region.
 */
function inList(target: EventTarget | null): boolean {
  if (target === document.body || target === document.documentElement) return true
  if (!(target instanceof Element)) return false
  return target.closest(LIST_REGION) !== null
}

/**
 * Run `event` against the map. Exported so the table can be tested as a
 * table, without a component around it.
 *
 * Returns whether the map took the key, which is what the caller would
 * need if a second listener ever sat behind this one; nothing does yet,
 * and the tests read it as "did anything happen".
 */
export function handleKey(event: KeyboardEvent, handlers: KeymapHandlers): boolean {
  // Something nearer the key has already dealt with it — a Radix dialog
  // consuming `esc`, a composer consuming `⏎`.
  if (event.defaultPrevented) return false

  // 1. `esc`, from anywhere. Not prevented: Radix closes its own dialogs
  //    on the same keystroke and this is the app agreeing with it, not
  //    overriding it.
  if (event.key === 'Escape' && !event.ctrlKey && !event.metaKey && !event.altKey) {
    handlers.close()
    return true
  }

  const cap = capOf(event)

  // 2. The chords, wherever the caret is.
  if (event.ctrlKey || event.metaKey) {
    if (cap === '^p') {
      event.preventDefault()
      handlers.openPalette()
      return true
    }
    const chord = actionFor(handlers.actions, cap)
    if (chord === undefined) return false
    // `^r` is the browser's reload before it is ours.
    event.preventDefault()
    chord.run()
    return true
  }

  // 3. The plain keys, suppressed while typing and while an overlay has
  //    the keyboard.
  if (isTyping(event) || keyboardOwned()) return false

  // `a` and `d` belong to the request panel the keystroke came from, and
  // to nothing else. Checked before the app's own keys so that a future
  // binding on either cap cannot quietly take them back.
  if (event.key === 'a' || event.key === 'd') {
    const answer = answerKeysAt(event.target)
    if (answer === null) return false
    const chosen = event.key === 'a' ? answer.allow : answer.deny
    if (chosen === null) return false
    event.preventDefault()
    chosen()
    return true
  }

  switch (event.key) {
    case 'ArrowDown':
    case 'j':
      event.preventDefault()
      if (handlers.runFocused) handlers.moveRun(1)
      else handlers.select(1)
      return true
    case 'ArrowUp':
    case 'k':
      event.preventDefault()
      if (handlers.runFocused) handlers.moveRun(-1)
      else handlers.select(-1)
      return true
    case 'ArrowRight':
      event.preventDefault()
      handlers.cyclePane(1)
      return true
    case 'ArrowLeft':
      event.preventDefault()
      handlers.cyclePane(-1)
      return true
    case 'Enter':
      if (!inList(event.target)) return false
      event.preventDefault()
      handlers.toggleRunFocus()
      return true
    default:
      break
  }

  if (event.key >= '1' && event.key <= String(JUMP_KEYS) && event.key.length === 1) {
    event.preventDefault()
    handlers.jumpPane(Number(event.key) - 1)
    return true
  }

  const action = actionFor(handlers.actions, cap)
  if (action === undefined) return false
  event.preventDefault()
  action.run()
  return true
}

/**
 * Bind the map for as long as the component is mounted.
 *
 * One listener on `window`, registered once: the handlers are read
 * through a ref, so a shell that re-renders on every event of every run
 * does not add and remove a listener each time.
 */
export function useKeymap(handlers: KeymapHandlers): void {
  const held = useRef(handlers)

  useEffect(() => {
    held.current = handlers
  })

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      handleKey(event, held.current)
    }

    window.addEventListener('keydown', onKeyDown)
    return () => {
      window.removeEventListener('keydown', onKeyDown)
    }
  }, [])
}

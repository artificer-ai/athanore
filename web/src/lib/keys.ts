/**
 * The keyboard map of `docs/v1/10-frontend.md` §Keyboard, as data.
 *
 * That section is one sentence long and exhaustive — "exactly the mock's
 * map, which is the TUI's" — and three parts of the app have to agree
 * with it: the footer strip's chips, the `?` overlay that is "the footer
 * chips, expanded" (10 §Overlays), and the handler that binds the keys
 * (T067). Three hand-written copies of one table is three places a new
 * binding can be forgotten, so there is one table and they are three
 * views of it.
 *
 * It lives in `lib/` because of who reads it: `components/Footer.tsx`
 * and `overlays/Keys.tsx` are on either side of the app's one import
 * direction (an overlay may reach into `components/`, and does), so the
 * table has to sit under both.
 *
 * **The rows are 10's, in 10's order, including the two the mock never
 * drew.** `D` is delete rather than the mock's `d`, so that a `d` meant
 * for "deny" one focus ring away cannot reach the delete confirm; `a`
 * and `d` themselves are the request panel's and are listed last, under
 * the scope that is the whole of their rule. A row's `keys` are the
 * keycaps it is drawn as, so "`↑`/`↓` or `j`/`k` select" is one binding
 * with four caps rather than four bindings — it is one thing the
 * operator can do.
 *
 * The groups are this file's, and they are only headings: they cut 10's
 * sentence at the points it already turns, and every row stays in the
 * order that sentence lists it, so reading the table top to bottom reads
 * the spec.
 *
 * A row's `keys` are the caps that are *bound* — the handler dispatches
 * on them directly — and {@link capLabel} is how they are *drawn*, so
 * none of the three views can advertise a keystroke nothing runs
 * (D207).
 */

/** The headings the `?` overlay draws its sections under. */
export const KEY_GROUPS = ['navigate', 'tasks', 'runs', 'app', 'requests'] as const

export type KeyGroup = (typeof KEY_GROUPS)[number]

/** One binding: the caps it is drawn as, what it does, and when. */
export type KeyBinding = {
  /** Stable and unique: the row's React key and a test's handle. */
  id: string
  /** The keycaps, in the order 10 writes them. */
  keys: readonly string[]
  /** What it does, in the footer's words. */
  label: string
  /** The section it is drawn under. */
  group: KeyGroup
  /**
   * When the binding applies, or `''` when it always does. Never
   * decoration: `a` and `d` are live only while the request panel has
   * focus, and `D` asks first.
   */
  note: string
  /** Whether the footer strip carries this one (10 §Layout). */
  footer: boolean
}

/** The shift chip: U+21E7, the strip's own arrow family. */
export const SHIFT_CAP = '⇧'

/**
 * A cap as the operator has to type it.
 *
 * The table's caps are 10 §Keyboard's and the handler dispatches on
 * them directly (`keys/useKeymap.ts` `capOf` returns `event.key`), so
 * `D` is what runs the delete confirm. `D` is also the one cap of this
 * map whose only difference from another cap in it is its case — which
 * is why D51 chose it — and a chip reading `D` in an interface whose
 * every other word is lowercase reads as the letter `d`, which is the
 * request panel's deny and reaches nothing else. So a cap that is one
 * uppercase letter is *drawn* with the shift chip and still *bound*
 * without it: the modifier is drawn, not bound (D207).
 */
export function capLabel(cap: string): string {
  return /^[A-Z]$/.test(cap) ? `${SHIFT_CAP}${cap}` : cap
}

/**
 * 10 §Keyboard, transcribed.
 *
 * Nothing is added and nothing is left out. The sentences that follow
 * the list in 10 are {@link KEY_NOTES}, because they are rules about the
 * map rather than rows in it — including the paragraph that says what
 * `↑`/`↓` mean while a run is focused, which is one binding's condition
 * and not a keycap of its own (D204 (3)).
 */
export const KEY_BINDINGS: readonly KeyBinding[] = [
  {
    id: 'select',
    keys: ['↑', '↓', 'j', 'k'],
    label: 'select',
    group: 'navigate',
    note: '',
    footer: false,
  },
  {
    id: 'move-run',
    keys: ['↑', '↓', 'j', 'k'],
    label: 'move run',
    group: 'navigate',
    note: 'while a run is focused',
    footer: false,
  },
  {
    id: 'cycle-panes',
    keys: ['←', '→'],
    label: 'cycle panes',
    group: 'navigate',
    note: '',
    footer: false,
  },
  {
    id: 'jump-pane',
    keys: ['1–9'],
    label: 'jump to a pane',
    group: 'navigate',
    note: '',
    footer: false,
  },
  {
    id: 'focus-run',
    keys: ['⏎'],
    label: 'focus run',
    group: 'navigate',
    note: '',
    footer: false,
  },
  { id: 'focus', keys: ['tab'], label: 'focus', group: 'navigate', note: '', footer: true },

  {
    id: 'retry-task',
    keys: ['t'],
    label: 'retry task',
    group: 'tasks',
    note: '',
    footer: true,
  },
  {
    id: 'move-task',
    keys: ['m'],
    label: 'move task',
    group: 'tasks',
    note: '',
    footer: true,
  },
  {
    id: 'cancel-task',
    keys: ['x'],
    label: 'cancel task',
    group: 'tasks',
    note: '',
    footer: true,
  },

  {
    id: 'append-log',
    keys: ['l'],
    label: 'append log',
    group: 'runs',
    note: '',
    footer: true,
  },
  { id: 'new-run', keys: ['n'], label: 'new run', group: 'runs', note: '', footer: true },
  {
    id: 'rerun-node',
    keys: ['r'],
    label: 'rerun node',
    group: 'runs',
    note: '',
    footer: true,
  },
  {
    id: 'pause-resume',
    keys: ['p'],
    label: 'pause/resume',
    group: 'runs',
    note: '',
    footer: true,
  },
  {
    id: 'cancel-run',
    keys: ['c'],
    label: 'cancel run',
    group: 'runs',
    note: '',
    footer: true,
  },
  {
    id: 'delete-run',
    keys: ['D'],
    label: 'delete run',
    group: 'runs',
    note: 'shift, and it asks first',
    footer: true,
  },
  {
    id: 'edit-run',
    keys: ['e'],
    label: 'edit run',
    group: 'runs',
    note: '',
    footer: true,
  },

  {
    id: 'workflows',
    keys: ['w'],
    label: 'workflows',
    group: 'app',
    note: '',
    footer: true,
  },
  {
    id: 'toggle-list',
    keys: ['b'],
    label: 'toggle list',
    group: 'app',
    note: '',
    footer: true,
  },
  { id: 'keys', keys: ['?'], label: 'keys', group: 'app', note: '', footer: true },
  { id: 'palette', keys: ['^p'], label: 'palette', group: 'app', note: '', footer: false },
  { id: 'refresh', keys: ['^r'], label: 'refresh', group: 'app', note: '', footer: false },
  { id: 'close', keys: ['esc'], label: 'close', group: 'app', note: '', footer: false },

  {
    id: 'allow',
    keys: ['a'],
    label: 'allow',
    group: 'requests',
    note: 'while the request panel has focus',
    footer: false,
  },
  {
    id: 'deny',
    keys: ['d'],
    label: 'deny',
    group: 'requests',
    note: 'while the request panel has focus',
    footer: false,
  },
]

/**
 * The rules 10 §Keyboard states about the map rather than in it.
 *
 * They are as much a part of "every binding" as the rows: an operator
 * who cannot find why `t` did nothing while they were typing a title has
 * not been told the map, and neither has one who cannot find why `↑`
 * moved a run instead of the cursor.
 */
export const KEY_NOTES: readonly string[] = [
  'shortcuts are suppressed inside inputs',
  'the pane index is clamped to the selected run’s pane count',
  '⏎ picks the selected run up; ↑↓ then move it in the dispatch list, and ⏎ or esc puts it down',
]

/** The footer strip's chips, in the map's order (10 §Layout). */
export const FOOTER_HINTS: readonly KeyBinding[] = KEY_BINDINGS.filter(
  (binding) => binding.footer,
)

/** The bindings of one group, in the map's order. */
export function bindingsOf(group: KeyGroup): KeyBinding[] {
  return KEY_BINDINGS.filter((binding) => binding.group === group)
}

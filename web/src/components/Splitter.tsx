/**
 * The splitter between the run list and the detail pane, and the rail the
 * list collapses to (`docs/v1/10-frontend.md` §Layout).
 *
 * Two ends bound the drag and neither is negotiable: the list is never
 * narrower than 260 px, and the detail pane never narrower than 340 px,
 * which is what makes the list's widest `window − 340`. The group holds
 * both while the pointer is down — the detail panel's own minimum is what
 * caps the list — and `usePrefs.setListWidth` clamps again on the way to
 * `localStorage`, so a width that survives a reload is a width that fits
 * the window it is reloaded into.
 *
 * The two regions and the handle between them are the page's `main`
 * landmark: 10 §Accessibility and quality asks for a clean axe run, and
 * a document with no `main` fails `landmark-one-main` while everything
 * between the header and the footer fails `region`. The element is here
 * rather than around this component because both branches below are the
 * whole of the app's body, and a wrapper would be one more flex box
 * between the shell and the panels.
 *
 * Collapsed, the list and the handle are replaced by the mock's 30 px
 * rail, which reads `RUNS n` sideways and expands the list again when it
 * is clicked. The `❮` that collapses it lives in the pane bar
 * (`./Detail`), where the mock puts it. Both write `listCollapsed`, which
 * is also where `b` binds in T067.
 *
 * **Stacked**, below the breakpoint, none of that is drawn: `stacked`
 * says which single region the middle is, the shell having read it off
 * `?run=` (21 §Narrow layout, D194). Neither `listWidth` nor
 * `listCollapsed` is written or cleared there — a phone visit leaves the
 * desktop geometry exactly as the operator left it — and the group is
 * not mounted at all, because 260 px of list and 340 px of detail do not
 * both fit in a phone.
 *
 * The stacked middle has a third value, **`global`**: the narrow global
 * screen, which is the same `detail` slot — the shell hands it a
 * `Detail` over the global cycle, exactly what the desktop draws with
 * nothing selected — marked `data-stacked="global"` (D216). The three
 * are one line — list, detail, global — and a horizontal swipe walks
 * it: left is one screen towards the list, right is one away from it
 * (D217). The gesture is read here, on the stacked `<main>` at every
 * narrow screen and nowhere else — the swipe is a property of the
 * stacked middle, and the desktop split is never listened to
 * (`../lib/useSwipe.ts`) — and what a direction means on the screen it
 * lands on is the shell's to decide.
 */
import { useRef, type ReactNode } from 'react'
import { Group, Panel, Separator } from 'react-resizable-panels'

import { useSwipe, type SwipeDirection } from '../lib/useSwipe'
import { MIN_DETAIL_WIDTH, MIN_LIST_WIDTH, usePrefs } from '../store/prefs'

/**
 * The panel ids. They are the keys of the group's layout and the `id`
 * attributes of the two panel elements, so they are written once.
 */
const LIST_PANEL = 'list-panel'
const DETAIL_PANEL = 'detail-panel'

export function Splitter({
  count,
  list,
  detail,
  stacked,
  onSwipe,
}: {
  /** Run rows on screen: what the collapsed rail reports. */
  count: number
  list: ReactNode
  detail: ReactNode
  /**
   * The one region to draw, below the breakpoint, or nothing at or
   * above it. `App` decides: `?run=` says list or detail (D194), and
   * `?global=` beside it says the global screen over that run (D216,
   * D217), which is the `detail` slot drawn again.
   */
  stacked?: 'list' | 'detail' | 'global' | undefined
  /**
   * A horizontal swipe on the stacked middle: `left` is one screen
   * towards the list, `right` is one away from it, and the shell drops
   * a direction that has no meaning on the screen it is on (D217). Read
   * only while stacked; the desktop split has no gesture.
   */
  onSwipe?: ((direction: SwipeDirection) => void) | undefined
}) {
  const listWidth = usePrefs((s) => s.listWidth)
  const listCollapsed = usePrefs((s) => s.listCollapsed)
  const setListWidth = usePrefs((s) => s.setListWidth)
  const setListCollapsed = usePrefs((s) => s.setListCollapsed)
  const listElement = useRef<HTMLDivElement | null>(null)
  const detailElement = useRef<HTMLDivElement | null>(null)
  // Attached to the stacked `<main>` below and to nothing else: the ref
  // is only ever set on that branch, so the split layouts, which never
  // render it, listen to nothing.
  const swipeRef = useSwipe(stacked === undefined ? undefined : onSwipe)

  // Narrow first: a `listCollapsed` the operator set on a desktop says
  // nothing about a viewport that has no list *and* detail to choose
  // between, and the rail is the collapsed half of a split that is not
  // drawn here.
  if (stacked !== undefined) {
    return (
      <main
        ref={swipeRef}
        data-stacked={stacked}
        className="flex min-h-0 min-w-0 flex-1 items-stretch"
      >
        {stacked === 'list' ? list : detail}
      </main>
    )
  }

  if (listCollapsed) {
    return (
      <main className="flex min-h-0 flex-1 items-stretch">
        <button
          type="button"
          onClick={() => setListCollapsed(false)}
          aria-label="show run list"
          title="show run list (b)"
          className="bg-chrome text-meta flex w-[30px] flex-none flex-col items-center gap-[10px] border-r border-border py-[10px] text-muted-foreground hover:bg-[var(--color-neutral-900)] hover:text-[var(--color-accent-200)]"
        >
          <span aria-hidden>❯</span>
          <span
            data-testid="runs-rail"
            className="text-hint tracking-[0.18em] [writing-mode:vertical-rl]"
          >
            RUNS {count}
          </span>
        </button>

        {detail}
      </main>
    )
  }

  return (
    <main className="flex min-h-0 flex-1 items-stretch">
      <Group
        id="layout"
        orientation="horizontal"
        /**
         * The pointer has been released (or a resize key pressed): the
         * width the operator settled on is theirs to keep. Every other
         * source — the initial mount, a window resize, the group
         * remounting when the rail expands — reports `false` and is left
         * alone, so a narrow window cannot quietly rewrite a width the
         * operator chose on a wide one.
         */
        onLayoutChanged={(layout, meta) => {
          if (!meta.isUserInteraction) return
          const share = layout[LIST_PANEL]
          const listBox = listElement.current
          const detailBox = detailElement.current
          if (share === undefined || !listBox || !detailBox) return
          // The share is a percentage of the two panels together, which
          // is the group less the handle. It is read rather than
          // measured because the DOM has not caught up with it yet: a
          // resize key changes the layout and the width in one go, and
          // `offsetWidth` would still be the width before the keystroke.
          setListWidth((share / 100) * (listBox.offsetWidth + detailBox.offsetWidth))
        }}
      >
        <Panel
          id={LIST_PANEL}
          elementRef={listElement}
          defaultSize={listWidth}
          minSize={MIN_LIST_WIDTH}
          // The list keeps its pixel width when the window is resized;
          // the detail pane, which has no stored width, absorbs the
          // difference until its own 340 px minimum takes over.
          groupResizeBehavior="preserve-pixel-size"
          className="flex min-h-0 min-w-0 flex-col"
          style={{ overflow: 'hidden' }}
        >
          {list}
        </Panel>

        {/* The mock's 5 px handle. It lights on hover and while it is
            being dragged; `data-separator` is the group's own state, and
            it covers the 10 px hit region the group actually watches
            rather than only the five pixels of the bar. */}
        <Separator
          id="list-splitter"
          aria-label="resize run list"
          title="drag to resize"
          className="w-[5px] cursor-col-resize bg-[var(--color-neutral-800)] focus-visible:outline-2 focus-visible:outline-[var(--color-accent)] data-[separator=active]:bg-[var(--color-accent-600)] data-[separator=hover]:bg-[var(--color-accent-700)]"
        />

        <Panel
          id={DETAIL_PANEL}
          elementRef={detailElement}
          minSize={MIN_DETAIL_WIDTH}
          className="flex min-h-0 min-w-0 flex-col"
          style={{ overflow: 'hidden' }}
        >
          {detail}
        </Panel>
      </Group>
    </main>
  )
}

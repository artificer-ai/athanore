/**
 * The app shell: the four regions of `docs/v1/10-frontend.md` §Layout —
 * header, run list, detail, footer.
 *
 * The list and the detail pane sit either side of `Splitter`, which owns
 * the width between them and the rail the list collapses to.
 *
 * Everything that makes this view *this view* comes in on `search`: the
 * shell owns no selection state of its own, and `onSelectRun` hands a
 * click back to the route, which writes `?run=`.
 *
 * `GET /api/runs` is read once, here, and shared: the header's counts,
 * the chips, the rows and the collapsed rail's `RUNS n` are four views of
 * one cached resource, so they cannot disagree and they refresh together
 * when `run.*` or `task.*` invalidates it (10 §Realtime and caching).
 *
 * `ServerDownBanner` sits directly under the header and renders nothing
 * while the event feed is up (10 §Realtime and caching).
 *
 * `useAttention` is read here for a third form of the same reason: the
 * tab title and the desktop notifications are one fact about the whole
 * app (10 §Attention), and the shell is the one component mounted for
 * exactly as long as the app is.
 *
 * `usePanes` is read here rather than inside `Detail` for the same
 * reason `GET /api/runs` is: the pane cycle's actions are the keyboard's
 * too (`←`, `→`, `1`–`9`, T067) and the palette's as well — `append log`
 * is "the log pane, with the caret in its composer" — and a shell that
 * holds the model can hand it to all of them without any of them owning
 * the others.
 *
 * The overlays hang off the shell rather than off whatever opened them,
 * because `?overlay=` is one piece of state and the thing it names is
 * over the whole app (10 §Overlays). They portal out of this tree, so
 * where they sit in it says nothing about where they draw. The header's
 * `＋ new run` is one more way of writing `?overlay=new`, beside the
 * palette's row and (T067) the `n` key.
 */
import { useQueryClient } from '@tanstack/react-query'

import { Detail } from './components/Detail'
import { Footer } from './components/Footer'
import { Header } from './components/Header'
import { RunList, useRunListModel } from './components/RunList'
import { ServerDownBanner } from './components/ServerDownBanner'
import { Splitter } from './components/Splitter'
import { useAttention } from './components/attention'
import { NewRun, Palette, buildPaletteActions } from './overlays'
import { BUILTIN_WORKFLOW, usePanes } from './panes'
import type { AppSearch, Overlay } from './routes/search'
import { usePrefs } from './store/prefs'
import { useUi } from './store/ui'

/** What a handler the shell was not given does. */
const NOTHING = () => {}

/** The builtin pane a graph row jumps to (10 §Graph pane, 09 §Builtins). */
const LOG_PANE = 'log'

export default function App({
  search,
  onSelectRun,
  onSelectPane,
  onOpenPalette,
  onOpenTask,
  onFilterNode,
  onOpenNode,
  onOpenOverlay,
  onCloseOverlay,
}: {
  search: AppSearch
  onSelectRun: (runId: string) => void
  onSelectPane: (index: number) => void
  onOpenPalette: () => void
  onOpenTask?: ((taskId: number) => void) | undefined
  onFilterNode?: ((node: string | undefined) => void) | undefined
  /**
   * `?node=` and `?pane=` in one navigation: a graph row "jumps to the
   * log pane filtered to that node" (10 §Graph pane), and the shell is
   * where the log pane's index is known.
   */
  onOpenNode?: ((node: string, pane: number | undefined) => void) | undefined
  /** Open an overlay by name; the graph's `open definition` opens one. */
  onOpenOverlay?: ((overlay: Overlay) => void) | undefined
  /** Close whichever overlay is up: `?overlay=` away (10 §Overlays). */
  onCloseOverlay?: (() => void) | undefined
}) {
  const runs = useRunListModel()
  useAttention()
  const panes = usePanes(search.run, { index: search.pane, onChange: onSelectPane })
  const queryClient = useQueryClient()
  const toggleListCollapsed = usePrefs((state) => state.toggleListCollapsed)
  const focusLogComposer = useUi((state) => state.focusLogComposer)

  // Which pane the log is, in *this* selection's cycle: the manifest
  // decides how many panes there are and a plugin's `log` panel is not
  // this one, so the index is looked up rather than assumed (09
  // §Builtins are plugins).
  const logPane = panes.panes.findIndex(
    (pane) => pane.workflow === BUILTIN_WORKFLOW && pane.name === LOG_PANE,
  )

  // The palette's rows are the app's own actions, so they are built here
  // rather than inside it: `refresh` is this tab's whole cache,
  // `toggle list` is the splitter's rail, and `append log` is the pane
  // cycle plus the caret — the shell is where all three are already in
  // hand (`overlays/actions.ts`).
  const paletteActions = buildPaletteActions({
    runId: search.run,
    openOverlay: onOpenOverlay ?? NOTHING,
    close: onCloseOverlay ?? NOTHING,
    refresh: () => {
      void queryClient.invalidateQueries()
    },
    toggleList: toggleListCollapsed,
    // `append log` writes nothing itself: the note is the log pane's
    // composer, which already posts it (`panes/kinds/Log.tsx`), so the
    // command is "show me that box and put me in it". The caret is asked
    // for through `useUi` because the composer is mounted by the pane
    // once its panel has answered, which is after this call returns; a
    // cycle with no log pane in it — a manifest still in flight — asks
    // for nothing rather than leaving a request nothing will serve.
    appendLog: () => {
      if (logPane < 0 || search.run === undefined) return
      panes.jump(logPane)
      focusLogComposer(search.run)
    },
  })

  return (
    <div className="text-body flex h-dvh flex-col overflow-hidden bg-background text-foreground">
      <Header
        runs={runs}
        onNewRun={() => {
          onOpenOverlay?.('new')
        }}
      />
      <ServerDownBanner />

      <Splitter
        count={runs.rows.length}
        list={
          <RunList model={runs} selected={search.run} onSelect={onSelectRun} />
        }
        detail={
          <Detail
            panes={panes}
            taskId={search.task}
            node={search.node}
            onOpenTask={onOpenTask}
            onFilterNode={onFilterNode}
            onOpenNode={
              onOpenNode === undefined
                ? undefined
                : (node) => {
                    onOpenNode(node, logPane < 0 ? undefined : logPane)
                  }
            }
            onOpenLibrary={
              onOpenOverlay === undefined
                ? undefined
                : () => {
                    onOpenOverlay('library')
                  }
            }
          />
        }
      />

      <Footer onOpenPalette={onOpenPalette} />

      <Palette
        open={search.overlay === 'palette'}
        actions={paletteActions}
        onClose={onCloseOverlay ?? NOTHING}
      />

      <NewRun open={search.overlay === 'new'} onClose={onCloseOverlay ?? NOTHING} />
    </div>
  )
}

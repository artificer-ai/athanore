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
 * `usePanes` is read here rather than inside `Detail` for the same
 * reason `GET /api/runs` is: the pane cycle's actions are the keyboard's
 * too (`←`, `→`, `1`–`9`, T067), and a shell that holds the model can
 * hand it to both without either owning the other.
 */
import { Detail } from './components/Detail'
import { Footer } from './components/Footer'
import { Header } from './components/Header'
import { RunList, useRunListModel } from './components/RunList'
import { ServerDownBanner } from './components/ServerDownBanner'
import { Splitter } from './components/Splitter'
import { BUILTIN_WORKFLOW, usePanes } from './panes'
import type { AppSearch, Overlay } from './routes/search'

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
}) {
  const runs = useRunListModel()
  const panes = usePanes(search.run, { index: search.pane, onChange: onSelectPane })

  // Which pane the log is, in *this* selection's cycle: the manifest
  // decides how many panes there are and a plugin's `log` panel is not
  // this one, so the index is looked up rather than assumed (09
  // §Builtins are plugins).
  const logPane = panes.panes.findIndex(
    (pane) => pane.workflow === BUILTIN_WORKFLOW && pane.name === LOG_PANE,
  )

  return (
    <div className="text-body flex h-dvh flex-col overflow-hidden bg-background text-foreground">
      <Header runs={runs} />
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
    </div>
  )
}

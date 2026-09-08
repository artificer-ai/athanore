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
import { usePanes } from './panes'
import type { AppSearch } from './routes/search'

export default function App({
  search,
  onSelectRun,
  onSelectPane,
  onOpenPalette,
  onOpenTask,
  onFilterNode,
}: {
  search: AppSearch
  onSelectRun: (runId: string) => void
  onSelectPane: (index: number) => void
  onOpenPalette: () => void
  onOpenTask?: ((taskId: number) => void) | undefined
  onFilterNode?: ((node: string | undefined) => void) | undefined
}) {
  const runs = useRunListModel()
  const panes = usePanes(search.run, { index: search.pane, onChange: onSelectPane })

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
          />
        }
      />

      <Footer onOpenPalette={onOpenPalette} />
    </div>
  )
}

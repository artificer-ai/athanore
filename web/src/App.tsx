/**
 * The app shell: the four regions of `docs/v1/10-frontend.md` §Layout —
 * header, run list, detail, footer.
 *
 * The list and the detail pane sit either side of `Splitter`, which owns
 * the width between them and the rail the list collapses to.
 *
 * Everything that makes this view *this view* comes in on `search`: the
 * shell owns no selection state of its own. The data does not arrive
 * until T059, so the counts on screen are the counts of what is on
 * screen, which is nothing.
 */
import { Detail } from './components/Detail'
import { Footer } from './components/Footer'
import { Header } from './components/Header'
import { RunList } from './components/RunList'
import { Splitter } from './components/Splitter'
import type { AppSearch } from './routes/search'

export default function App({
  search,
  onOpenPalette,
}: {
  search: AppSearch
  onOpenPalette: () => void
}) {
  /**
   * The number of run rows on screen. T061 renders the rows of
   * `GET /api/runs` here and this becomes their count; until then the
   * list renders none, and `0` is the honest report of that rather than
   * a placeholder standing in for a number nobody has.
   */
  const runCount = 0

  return (
    <div className="text-body flex h-dvh flex-col overflow-hidden bg-background text-foreground">
      <Header />

      <Splitter
        count={runCount}
        list={<RunList count={runCount} />}
        detail={<Detail search={search} />}
      />

      <Footer onOpenPalette={onOpenPalette} />
    </div>
  )
}

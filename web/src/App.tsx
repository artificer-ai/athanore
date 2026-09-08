/**
 * The app shell: the four regions of `docs/v1/10-frontend.md` §Layout —
 * header, run list, detail, footer.
 *
 * The run list is laid out at the width `usePrefs` holds; the splitter
 * that lets the operator drag it, and the rail it collapses to, are
 * T058a's.
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
import type { AppSearch } from './routes/search'
import { MIN_DETAIL_WIDTH, usePrefs } from './store/prefs'

export default function App({
  search,
  onOpenPalette,
}: {
  search: AppSearch
  onOpenPalette: () => void
}) {
  const listWidth = usePrefs((s) => s.listWidth)

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

      <div className="flex min-h-0 flex-1 items-stretch">
        <div
          className="flex min-h-0 min-w-0 flex-none flex-col"
          // The detail pane keeps its 340 px however wide the list is
          // (10 §Layout), which on a narrow window is the binding end.
          style={{ width: listWidth, maxWidth: `calc(100% - ${MIN_DETAIL_WIDTH}px)` }}
        >
          <RunList count={runCount} />
        </div>

        <Detail search={search} />
      </div>

      <Footer onOpenPalette={onOpenPalette} />
    </div>
  )
}

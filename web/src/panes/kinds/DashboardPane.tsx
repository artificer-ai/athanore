/**
 * `dashboard`: `{note?, metrics, table?}` — "the design mock's plugin
 * pane: a note, metric tiles, a table" (09 §Panel kinds).
 *
 * It is a composition and nothing else: the note is prose, the tiles are
 * {@link MetricGrid}, and the table is the `table` kind's own renderer,
 * so a plugin's table sorts here exactly as it does in a pane of its
 * own.
 *
 * The overview builtin sends a fourth key, `meta`, and this renderer
 * ignores it — deliberately. Its own module says so: "A renderer that
 * knows only the `dashboard` kind draws the first three and ignores the
 * fourth; the SPA's own overview renderer draws all of it"
 * (`athanore/plugins/builtin/overview.py`; 15, D140 (3)). That other
 * renderer is T063a's. Drawing `meta` here would make it part of the
 * kind, which it is not.
 */
import { MetricGrid } from './MetricGrid'
import { TablePane } from './TablePane'
import type { DashboardData } from './shape'

export function DashboardPane({ data }: { data: DashboardData }) {
  return (
    <div data-testid="pane-dashboard" className="flex flex-col gap-[14px]">
      {data.note !== undefined && data.note !== '' && (
        <p className="text-row max-w-[620px] text-muted-foreground">{data.note}</p>
      )}
      <MetricGrid metrics={data.metrics} />
      {data.table !== undefined && <TablePane data={data.table} />}
    </div>
  )
}

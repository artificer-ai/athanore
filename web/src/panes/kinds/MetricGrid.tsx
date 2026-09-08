/**
 * The mock's metric tiles: a 1 px-gapped grid on a neutral-900 ground,
 * each tile a kicker label over a 15 px value (10 §Type and density,
 * §Components — "custom `MetricGrid` (1 px gap grid)").
 *
 * The `dashboard` kind draws its `metrics` with it (09 §Panel kinds) and
 * so does the overview's STATS row (T063a): they are the same tiles in
 * the same grid, and drawing them twice is how the two would come to
 * differ.
 *
 * A metric whose value is absent is *not* shown as a zero — the source
 * omits what it does not know (01 §Real data only) — so an empty list
 * renders nothing at all rather than an empty frame.
 */
import { formatValue } from './format'
import type { Metric } from './shape'

export function MetricGrid({
  metrics,
  label = 'metrics',
}: {
  metrics: readonly Metric[]
  /** What a screen reader calls this grid; the mock has no visible one. */
  label?: string
}) {
  if (metrics.length === 0) return null

  return (
    <dl
      aria-label={label}
      data-testid="metric-grid"
      className="grid grid-cols-[repeat(auto-fit,minmax(120px,1fr))] gap-px overflow-hidden rounded-lg border border-[var(--color-neutral-900)] bg-[var(--color-neutral-900)]"
    >
      {metrics.map((metric) => (
        <div key={metric.label} className="bg-card px-[10px] py-[8px]">
          <dt className="text-hint tracking-[0.1em] text-muted-foreground">
            {metric.label}
          </dt>
          <dd className="text-metric mt-[3px] text-foreground">
            {formatValue(metric.value)}
          </dd>
        </div>
      ))}
    </dl>
  )
}

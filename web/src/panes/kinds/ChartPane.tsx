/**
 * `chart`: `{series: [{name, points: [[x, y]]}], kind: line|bar}` as a
 * small SVG (09 §Panel kinds — "small chart (new; the MVP's stats
 * bars)").
 *
 * **No charting library.** What 09 asks for is one plot of a handful of
 * series with no axes, no zoom and no tooltips; every library that could
 * draw it is larger than the SPA's own bundle and brings a second
 * theming system to keep in step with Nocturne. The maths is a linear
 * scale from the data's own extent onto a `viewBox`, which is the whole
 * of the file below.
 *
 * Colours are `--chart-1…3` (10 §Tokens → shadcn), cycled: three is what
 * the design system defines, and a fourth series repeats the first
 * rather than inventing a hue the theme has no name for.
 *
 * The extent is always the data's, never zero-based, except that bars
 * are drawn from zero because a bar's length is its value — a bar chart
 * with a floating baseline would misstate every value in it (01 §Real
 * data only).
 */
import { cn } from '../../lib/utils'
import { HEIGHT, PAD, WIDTH, extent, padExtent, scale, seriesColour } from './chart'
import { formatValue } from './format'
import type { ChartData } from './shape'

export function ChartPane({ data }: { data: ChartData }) {
  const drawable = data.series.filter((one) => one.points.length > 0)
  if (drawable.length === 0) {
    return (
      <p className="text-row text-muted-foreground" role="status">
        nothing to chart
      </p>
    )
  }

  const plotWidth = WIDTH - PAD.left - PAD.right
  const plotHeight = HEIGHT - PAD.top - PAD.bottom
  const [xLow, xHigh] = padExtent(extent(drawable, 0))
  const [rawLow, rawHigh] = extent(drawable, 1)
  // Bars measure from zero; a line shows the band its values live in.
  const [yLow, yTop] = padExtent(
    data.kind === 'bar'
      ? [Math.min(0, rawLow), Math.max(0, rawHigh)]
      : [rawLow, rawHigh],
  )

  const x = (value: number) => PAD.left + scale(value, xLow, xHigh, plotWidth)
  const y = (value: number) =>
    PAD.top + plotHeight - scale(value, yLow, yTop, plotHeight)

  const columns = Math.max(...drawable.map((one) => one.points.length))
  const slot = plotWidth / Math.max(columns, 1)
  const barWidth = Math.max(1, (slot * 0.7) / drawable.length)

  return (
    <div data-testid="pane-chart" className="flex flex-col gap-[8px]">
      <svg
        role="img"
        aria-label={`${data.kind} chart of ${drawable.map((one) => one.name).join(', ')}`}
        viewBox={`0 0 ${String(WIDTH)} ${String(HEIGHT)}`}
        preserveAspectRatio="none"
        className={cn(
          'bg-zebra h-[160px] w-full rounded-lg border border-[var(--color-neutral-900)]',
        )}
      >
        {/* The zero line, where zero is inside the extent at all. */}
        {yLow < 0 && yTop > 0 && (
          <line
            x1={PAD.left}
            x2={WIDTH - PAD.right}
            y1={y(0)}
            y2={y(0)}
            stroke="var(--color-neutral-800)"
            strokeWidth={1}
            vectorEffect="non-scaling-stroke"
          />
        )}

        {drawable.map((one, index) =>
          data.kind === 'bar' ? (
            <g key={one.name} data-series={one.name}>
              {one.points.map((point, slotIndex) => {
                const top = Math.min(y(point[1]), y(0))
                const height = Math.abs(y(point[1]) - y(0))
                return (
                  <rect
                    key={slotIndex}
                    x={
                      PAD.left +
                      slotIndex * slot +
                      (slot - barWidth * drawable.length) / 2 +
                      index * barWidth
                    }
                    y={top}
                    width={barWidth}
                    height={Math.max(height, 1)}
                    fill={seriesColour(index)}
                  />
                )
              })}
            </g>
          ) : (
            <polyline
              key={one.name}
              data-series={one.name}
              fill="none"
              stroke={seriesColour(index)}
              strokeWidth={1.5}
              vectorEffect="non-scaling-stroke"
              points={one.points
                .map((point) => `${String(x(point[0]))},${String(y(point[1]))}`)
                .join(' ')}
            />
          ),
        )}
      </svg>

      <div className="text-hint flex flex-wrap items-center gap-x-[12px] gap-y-[4px] text-muted-foreground">
        {drawable.map((one, index) => (
          <span key={one.name} className="inline-flex items-center gap-[5px]">
            <span
              aria-hidden="true"
              className="inline-block h-[6px] w-[6px] rounded-lg"
              style={{ backgroundColor: seriesColour(index) }}
            />
            {one.name}
          </span>
        ))}
        <div className="flex-1" />
        <span>
          {formatValue(yLow)} … {formatValue(yTop)}
        </span>
      </div>
    </div>
  )
}

/**
 * The plot's coordinate space and the linear scale onto it.
 *
 * The maths of `./ChartPane.tsx`, in a module of its own so that the
 * component file exports only its component (`.oxlintrc.json`,
 * `react/only-export-components`) — and so that the scaling can be
 * tested without rendering an SVG.
 */
import type { ChartSeries } from './shape'

/** The plot's coordinate space; the SVG scales to the pane's width. */
export const WIDTH = 600
export const HEIGHT = 160
export const PAD = { top: 8, right: 8, bottom: 8, left: 8 }

/** The three series colours 10 §Tokens → shadcn defines, in order. */
export const COLOURS = ['var(--chart-1)', 'var(--chart-2)', 'var(--chart-3)']

/** A series' colour, cycled: three is what the design system defines. */
export function seriesColour(index: number): string {
  return COLOURS[index % COLOURS.length] ?? COLOURS[0] ?? 'currentColor'
}

/** The smallest and largest value on one axis, over every series. */
export function extent(
  series: readonly ChartSeries[],
  axis: 0 | 1,
): [number, number] {
  let low = Number.POSITIVE_INFINITY
  let high = Number.NEGATIVE_INFINITY
  for (const one of series) {
    for (const point of one.points) {
      low = Math.min(low, point[axis])
      high = Math.max(high, point[axis])
    }
  }
  if (!Number.isFinite(low) || !Number.isFinite(high)) return [0, 1]
  return [low, high]
}

/**
 * A span with something in it.
 *
 * A flat series still has to be drawn, and a zero span is a division by
 * zero: it gets a band to sit in the middle of. Applied to the extent
 * the plot is actually scaled by, never to the extent itself — a bar
 * chart's is `[0, high]` and padding *that* would misstate the bars.
 */
export function padExtent([low, high]: [number, number]): [number, number] {
  return low === high ? [low - 0.5, high + 0.5] : [low, high]
}

/** A value on `[low, high]` as a fraction of the plot's `span` pixels. */
export function scale(
  value: number,
  low: number,
  high: number,
  span: number,
): number {
  return ((value - low) / (high - low)) * span
}

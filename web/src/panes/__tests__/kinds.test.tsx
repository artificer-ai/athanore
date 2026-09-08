/**
 * The renderers of 09 §Panel kinds, each over that section's own data
 * shape (`./fixtures.ts` — `SAMPLES`).
 *
 * Every sample goes through the narrowing function the renderer is
 * reached by in `PaneRenderer`, so a shape the document changes fails
 * here as a `null` rather than as a render nobody looked at.
 */
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  ChartPane,
  DashboardPane,
  KvPane,
  LogPane,
  MarkdownPane,
  MetricGrid,
  TablePane,
  asChart,
  asDashboard,
  asKv,
  asLog,
  asMarkdown,
  asTable,
  compareValues,
  extent,
  formatValue,
  nextSort,
  padExtent,
  rowTime,
} from '../kinds'
import { SAMPLES } from './fixtures'

/** A narrowed sample, or a failure that names the kind that drifted. */
function narrowed<T>(kind: string, value: T | null): T {
  if (value === null) throw new Error(`the ${kind} sample of 09 no longer narrows`)
  return value
}

describe('markdown', () => {
  it('renders 09’s sample as GitHub-flavoured prose', () => {
    render(<MarkdownPane text={narrowed('markdown', asMarkdown(SAMPLES.markdown))} />)

    expect(screen.getByRole('heading', { name: 'playtest' })).toBeInTheDocument()
    expect(screen.getByText('frame timing')).toBeInTheDocument()
    // The gfm table is the plugin: without `remark-gfm` these are pipes.
    expect(screen.getByRole('columnheader', { name: 'session' })).toBeInTheDocument()
    expect(screen.getByRole('cell', { name: 's-03' })).toBeInTheDocument()
  })

  it('shows a fenced block before shiki has loaded, and never nothing', () => {
    render(<MarkdownPane text={'```python\nassert fps > 55\n```'} />)

    const block = screen.getByTestId('code-block')
    expect(block).toHaveAttribute('data-highlighted', 'false')
    expect(block).toHaveTextContent('assert fps > 55')
  })

  it('refuses anything that is not a string', () => {
    expect(asMarkdown({ text: 'no' })).toBeNull()
  })
})

describe('kv', () => {
  it('renders 09’s sample as a two-column description list', () => {
    render(<KvPane data={narrowed('kv', asKv(SAMPLES.kv))} />)

    expect(screen.getByText('IMAGE')).toBeInTheDocument()
    expect(screen.getByText('py312')).toBeInTheDocument()
    expect(screen.getByText('MOUNTS')).toBeInTheDocument()
    expect(screen.getByText('3')).toBeInTheDocument()
    // Absent is `—`, never a zero (01 §Real data only).
    expect(screen.getByText('—')).toBeInTheDocument()
  })

  it('refuses a list, which is the log kind’s shape', () => {
    expect(asKv([{ ts: 'x', text: 'y' }])).toBeNull()
  })
})

describe('table', () => {
  const data = () => narrowed('table', asTable(SAMPLES.table))

  it('renders 09’s sample with its columns and rows', () => {
    render(<TablePane data={data()} />)

    expect(screen.getByRole('columnheader', { name: /SESSION/ })).toBeInTheDocument()
    expect(screen.getAllByRole('row')).toHaveLength(5)
    expect(screen.getByRole('cell', { name: 's-01' })).toBeInTheDocument()
    expect(screen.getByRole('cell', { name: '59.8' })).toBeInTheDocument()
  })

  it('sorts on a click, reverses on a second and restores on a third', async () => {
    const user = userEvent.setup()
    render(<TablePane data={data()} />)

    const order = () =>
      screen
        .getAllByRole('row')
        .slice(1)
        .map((row) => within(row).getAllByRole('cell')[0]?.textContent)

    expect(order()).toEqual(['s-01', 's-02', 's-03', 's-04'])

    await user.click(screen.getByRole('button', { name: /FPS/ }))
    // `null` sorts last ascending: an unknown is not a zero.
    expect(order()).toEqual(['s-04', 's-02', 's-01', 's-03'])

    await user.click(screen.getByRole('button', { name: /FPS/ }))
    expect(order()).toEqual(['s-03', 's-01', 's-02', 's-04'])

    await user.click(screen.getByRole('button', { name: /FPS/ }))
    // The source's own order is information: it comes back.
    expect(order()).toEqual(['s-01', 's-02', 's-03', 's-04'])
  })

  it('says which way a column is sorted', async () => {
    const user = userEvent.setup()
    render(<TablePane data={data()} />)

    await user.click(screen.getByRole('button', { name: /OUTCOME/ }))

    expect(screen.getByRole('columnheader', { name: /OUTCOME/ })).toHaveAttribute(
      'aria-sort',
      'ascending',
    )
  })

  it('cycles none → asc → desc → none on one column, and asc on another', () => {
    expect(nextSort(null, 'fps')).toEqual({ key: 'fps', direction: 'asc' })
    expect(nextSort({ key: 'fps', direction: 'asc' }, 'fps')).toEqual({
      key: 'fps',
      direction: 'desc',
    })
    expect(nextSort({ key: 'fps', direction: 'desc' }, 'fps')).toBeNull()
    expect(nextSort({ key: 'fps', direction: 'desc' }, 'session')).toEqual({
      key: 'session',
      direction: 'asc',
    })
  })

  it('refuses a column with no key and rows that are not objects', () => {
    expect(asTable({ columns: [{ label: 'FPS' }], rows: [] })).toBeNull()
    expect(asTable({ columns: [{ key: 'fps' }], rows: ['s-01'] })).toBeNull()
  })
})

describe('log', () => {
  /**
   * jsdom performs no layout and the virtualiser measures the DOM: this
   * is the viewport it measures, stated by the test as the splitter's
   * geometry is (`components/__tests__/Splitter.test.tsx`).
   */
  const original = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'offsetHeight')

  beforeEach(() => {
    // `@tanstack/react-virtual` sizes both the viewport and every row it
    // measures from `offsetHeight`: a 400 px scroller over 18 px rows.
    Object.defineProperty(HTMLElement.prototype, 'offsetHeight', {
      configurable: true,
      get(this: HTMLElement) {
        return this.dataset['testid'] === 'log-scroller' ? 400 : 18
      },
    })
    // jsdom implements no scrolling; tailing only has to ask for it.
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', {
      configurable: true,
      value: vi.fn(),
    })
  })

  afterEach(() => {
    if (original) Object.defineProperty(HTMLElement.prototype, 'offsetHeight', original)
  })

  it('renders 09’s sample rows with their time, source and tone', () => {
    render(<LogPane rows={narrowed('log', asLog(SAMPLES.log))} />)

    expect(screen.getByTestId('log-count')).toHaveTextContent('4 lines')
    expect(screen.getByText('engineering → qa')).toBeInTheDocument()
    expect(screen.getByText('[stats] 12480 tokens')).toBeInTheDocument()
    expect(screen.getAllByText('engineering/agent')).toHaveLength(2)
  })

  it('tails by default and stops when the toggle is pressed', async () => {
    const user = userEvent.setup()
    render(<LogPane rows={narrowed('log', asLog(SAMPLES.log))} />)

    const toggle = screen.getByTestId('log-tailing')
    expect(toggle).toHaveAttribute('aria-pressed', 'true')
    expect(toggle).toHaveTextContent('tailing')

    await user.click(toggle)

    expect(toggle).toHaveAttribute('aria-pressed', 'false')
    expect(toggle).toHaveTextContent('paused')
  })

  it('says so rather than drawing an empty scroller', () => {
    render(<LogPane rows={[]} />)

    expect(screen.getByRole('status')).toHaveTextContent('nothing logged yet')
  })

  it('shows a timestamp it cannot parse rather than NaN', () => {
    expect(rowTime('not a time')).toBe('not a time')
  })

  it('refuses a row with no text', () => {
    expect(asLog([{ ts: '2026-09-08T09:00:00Z' }])).toBeNull()
  })
})

describe('chart', () => {
  it('renders 09’s sample as one polyline per series', () => {
    const data = narrowed('chart', asChart(SAMPLES.chart))
    const { container } = render(<ChartPane data={data} />)

    const line = container.querySelector('polyline[data-series="fps"]')
    expect(line).not.toBeNull()
    // Four points, and the y extent is the data's own: 57.2 … 61.
    expect(line?.getAttribute('points')?.split(' ')).toHaveLength(4)
    expect(screen.getByText('57.2 … 61')).toBeInTheDocument()
  })

  it('draws bars from zero, because a bar’s length is its value', () => {
    const data = narrowed(
      'chart',
      asChart({ series: [{ name: 'crashes', points: [[1, 3]] }], kind: 'bar' }),
    )
    const { container } = render(<ChartPane data={data} />)

    expect(container.querySelectorAll('rect')).toHaveLength(1)
    expect(screen.getByText('0 … 3')).toBeInTheDocument()
  })

  it('gives a flat series a band to sit in rather than dividing by zero', () => {
    expect(extent([{ name: 'flat', points: [[1, 5]] }], 1)).toEqual([5, 5])
    expect(padExtent([5, 5])).toEqual([4.5, 5.5])
    // A bar chart's own span is never padded: `[0, 3]` means `[0, 3]`.
    expect(padExtent([0, 3])).toEqual([0, 3])
  })

  it('says so when every series is empty', () => {
    render(<ChartPane data={{ series: [{ name: 'fps', points: [] }], kind: 'line' }} />)

    expect(screen.getByRole('status')).toHaveTextContent('nothing to chart')
  })

  it('refuses a point that is not a pair of numbers', () => {
    expect(asChart({ series: [{ name: 'fps', points: [[1, 'x']] }] })).toBeNull()
  })
})

describe('dashboard', () => {
  it('renders 09’s sample as a note, tiles and a table', () => {
    const data = narrowed('dashboard', asDashboard(SAMPLES.dashboard))
    render(<DashboardPane data={data} />)

    expect(screen.getByText(/Runs the build headless/)).toBeInTheDocument()
    const tiles = screen.getByTestId('metric-grid')
    expect(within(tiles).getByText('SESSIONS')).toBeInTheDocument()
    expect(within(tiles).getByText('58.4')).toBeInTheDocument()
    expect(screen.getByRole('cell', { name: 's-01' })).toBeInTheDocument()
  })

  it('ignores the overview’s `meta`, which is not part of the kind', () => {
    // `athanore/plugins/builtin/overview.py` (15, D140 (3)): a renderer
    // that knows only the `dashboard` kind draws the first three keys;
    // the SPA's own overview renderer (T063a) draws the fourth.
    const data = narrowed(
      'dashboard',
      asDashboard({ metrics: [{ label: 'TOKENS', value: 12 }], meta: { RUN: '01JD' } }),
    )
    render(<DashboardPane data={data} />)

    expect(screen.queryByText('01JD')).toBeNull()
    expect(screen.getByText('TOKENS')).toBeInTheDocument()
  })

  it('draws no frame at all where there is no metric to put in it', () => {
    render(<MetricGrid metrics={[]} />)

    expect(screen.queryByTestId('metric-grid')).toBeNull()
  })

  it('refuses a table it cannot draw rather than dropping it', () => {
    expect(asDashboard({ metrics: [], table: { columns: 'no', rows: [] } })).toBeNull()
  })
})

describe('values', () => {
  it('prints a number as the source sent it, minus the float noise', () => {
    expect(formatValue(12480)).toBe('12480')
    expect(formatValue(12.300000000000001)).toBe('12.3')
    expect(formatValue(null)).toBe('—')
    expect(formatValue(true)).toBe('true')
  })

  it('sorts numbers by size and everything else by text', () => {
    expect(compareValues(9, 10)).toBeLessThan(0)
    expect(compareValues('9', '10')).toBeGreaterThan(0)
    expect(compareValues(null, 1)).toBeGreaterThan(0)
  })
})

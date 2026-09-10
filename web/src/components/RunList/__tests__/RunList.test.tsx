import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { RunStatus, RunSummary } from '../../../api/gen/types.gen'
import { narrowViewport, wideViewport } from '../../../lib/__tests__/fixtures'
import { useUi } from '../../../store/ui'
import { RunList } from '../RunList'
import { toRow, type RunListModel, type RunRow } from '../useRunList'

/** The instant the fixtures' ages are measured from. */
const NOW = Date.parse('2026-09-08T09:00:00Z')

function summary(over: Partial<RunSummary> = {}): RunSummary {
  return {
    id: '01JD5XABCDEFGHJKMNPQRSTVWX',
    workflow: 'feature_build',
    title: 'rebuild run detail as a web pane set',
    status: 'running',
    position: 1,
    created: '2026-09-08T08:56:00Z',
    updated: '2026-09-08T08:59:00Z',
    ...over,
  }
}

function row(over: Partial<RunSummary> = {}): RunRow {
  return toRow(summary(over), NOW)
}

function model(rows: RunRow[], over: Partial<RunListModel> = {}): RunListModel {
  return {
    rows,
    total: rows.length,
    active: 0,
    workflows: [],
    isPending: false,
    isError: false,
    ...over,
  }
}

function list(over: {
  rows?: RunRow[]
  model?: Partial<RunListModel>
  selected?: string
  focusedRun?: string
  onSelect?: (runId: string) => void
} = {}) {
  return render(
    <RunList
      model={model(over.rows ?? [row()], over.model)}
      selected={over.selected}
      focusedRun={over.focusedRun}
      onSelect={over.onSelect ?? (() => {})}
    />,
  )
}

function rows() {
  return within(screen.getByRole('listbox', { name: 'run rows' })).queryAllByRole(
    'option',
  )
}

describe('RunList', () => {
  beforeEach(() => {
    useUi.setState({ focus: 'list' })
  })

  it('renders the six columns of the mock and the footer strip', () => {
    list({ rows: [row(), row({ id: 'B', title: 'second' })] })

    for (const heading of ['RUN', 'WORKFLOW', 'TITLE', 'STATUS', 'NODE', 'AGE']) {
      expect(screen.getByText(heading)).toBeInTheDocument()
    }
    expect(screen.getByTestId('rows-shown')).toHaveTextContent('2 shown')
    expect(screen.getByText('↑↓ select')).toBeInTheDocument()
    expect(screen.getByText('⏎ focus run')).toBeInTheDocument()
  })

  it('shortens the run id to eight characters and keeps the whole one', () => {
    list()

    const [only] = rows()
    expect(only).toHaveTextContent('01JD5XAB')
    expect(only).toHaveAttribute('title', '01JD5XABCDEFGHJKMNPQRSTVWX')
  })

  it('joins the nodes a fanned-out run is in, and says so when it is in none', () => {
    list({
      rows: [
        row({ id: 'A', current_nodes: ['review', 'qa'] }),
        row({ id: 'B', status: 'completed', current_nodes: [] }),
      ],
    })

    expect(rows()[0]).toHaveTextContent('review · qa')
    expect(rows()[1]).toHaveTextContent('—')
  })

  it('marks a run with unanswered requests with ⚠, and no other', () => {
    list({
      rows: [
        row({ id: 'A', current_nodes: ['review'], pending_requests: 2 }),
        row({ id: 'B', current_nodes: ['qa'], pending_requests: 0 }),
      ],
    })

    expect(rows()[0]).toHaveTextContent('⚠')
    expect(rows()[1]).not.toHaveTextContent('⚠')
    expect(screen.getByTitle('2 waiting on you')).toBeInTheDocument()
  })

  it.each<[RunStatus, string]>([
    ['queued', 'text-status-queued'],
    ['running', 'text-status-active'],
    ['paused', 'text-status-paused'],
    ['completed', 'text-status-ok'],
    ['failed', 'text-status-fail'],
    ['cancelled', 'text-status-muted'],
  ])('writes the %s pill in %s', (status, className) => {
    list({ rows: [row({ status })] })

    const pill = screen.getByText(status)
    expect(pill).toHaveClass(className)
  })

  it('gives the pill of a run waiting on a person the gate colour', () => {
    list({ rows: [row({ status: 'running', pending_requests: 1 })] })

    const pill = screen.getByText('running')
    expect(pill).toHaveClass('text-status-gate')
    // The gate row of 10 §Status colours is plain: nothing is moving.
    expect(pill).not.toHaveClass('animate-ath-pulse')
  })

  it('pulses the running pill and nothing else', () => {
    list({ rows: [row({ status: 'running' }), row({ id: 'B', status: 'completed' })] })

    expect(screen.getByText('running')).toHaveClass('animate-ath-pulse')
    expect(screen.getByText('completed')).not.toHaveClass('animate-ath-pulse')
  })

  it('zebra-stripes every other row', () => {
    list({ rows: [row({ id: 'A' }), row({ id: 'B' }), row({ id: 'C' })] })

    const [first, second, third] = rows()
    expect(first).not.toHaveClass('bg-zebra')
    expect(second).toHaveClass('bg-zebra')
    expect(third).not.toHaveClass('bg-zebra')
  })

  it('gives the selected row the accent tint and the 2 px accent border', () => {
    list({ rows: [row({ id: 'A' }), row({ id: 'B' })], selected: 'B' })

    const [unselected, selected] = rows()
    expect(selected).toHaveAttribute('aria-selected', 'true')
    expect(selected).toHaveClass(
      'border-l-[var(--color-accent)]',
      'bg-[color-mix(in_srgb,var(--color-accent)_12%,var(--color-surface))]',
    )
    expect(unselected).toHaveAttribute('aria-selected', 'false')
    expect(unselected).toHaveClass('border-l-transparent')
  })

  it('draws the focused row in the second accent, and no other row', () => {
    list({ rows: [row({ id: 'A' }), row({ id: 'B' })], selected: 'B', focusedRun: 'B' })

    const [other, held] = rows()
    expect(held).toHaveAttribute('data-run-focused', 'true')
    // The mode is chrome and not fill: the left border and an inset
    // ring in the second accent, over the selection's own tint.
    expect(held).toHaveClass(
      'border-l-[var(--color-accent-2-400)]',
      'inset-ring-1',
      'inset-ring-[var(--color-accent-2-400)]',
    )
    // The fill is the selected row's, unchanged. It has to be: the
    // status pill paints `text-status-*` straight onto it, and a lighter
    // tint takes `fail` and `muted` under AA (10 §Accessibility and
    // quality, D204 (5)).
    expect(held).toHaveClass(
      'bg-[color-mix(in_srgb,var(--color-accent)_12%,var(--color-surface))]',
    )
    // The selection's border is replaced, not layered under it.
    expect(held).not.toHaveClass('border-l-[var(--color-accent)]')
    // It is still the selected run: `⏎` picks the selection up, and
    // `aria-selected` is what a screen reader is told (D204 (2)).
    expect(held).toHaveAttribute('aria-selected', 'true')

    expect(other).toHaveAttribute('data-run-focused', 'false')
    expect(other).toHaveClass('border-l-transparent')
  })

  it('swaps the strip’s two hints while a run is held, in a live region', () => {
    const { rerender } = list({ rows: [row({ id: 'A' })], selected: 'A' })

    expect(screen.getByText('↑↓ select')).toBeInTheDocument()
    expect(screen.getByText('⏎ focus run')).toBeInTheDocument()

    rerender(
      <RunList
        model={model([row({ id: 'A' })])}
        selected="A"
        focusedRun="A"
        onSelect={() => {}}
      />,
    )

    const strip = screen.getByTestId('list-hints')
    expect(strip).toHaveAttribute('role', 'status')
    expect(within(strip).getByText('↑↓ move run')).toBeInTheDocument()
    expect(within(strip).getByText('⏎/esc done')).toBeInTheDocument()
    expect(screen.queryByText('↑↓ select')).toBeNull()
    // `n shown` is not part of the mode, so it stays out of the region.
    expect(strip).not.toHaveTextContent('shown')
  })

  it('hands a clicked row back to the route, which writes ?run=', async () => {
    const onSelect = vi.fn()
    list({ rows: [row({ id: 'A' }), row({ id: 'B' })], onSelect })

    await userEvent.click(rows()[1]!)
    expect(onSelect).toHaveBeenCalledWith('B')
  })

  it('takes focus when it is clicked', async () => {
    useUi.setState({ focus: 'detail' })
    list()

    await userEvent.click(screen.getByRole('region', { name: 'runs' }))
    expect(useUi.getState().focus).toBe('list')
  })

  it('says it is still asking rather than showing an empty list', () => {
    list({ rows: [], model: { isPending: true, total: null, active: null } })

    // The strip's hints are a live region too, so the empty state is
    // named rather than taken as "the one status on screen".
    expect(screen.getByText('loading runs…')).toHaveAttribute('role', 'status')
    expect(screen.getByTestId('rows-shown')).toHaveTextContent('0 shown')
  })

  it('says a failed request failed rather than reading as no runs', () => {
    list({ rows: [], model: { isError: true, total: null, active: null } })

    expect(screen.getByText('could not load runs')).toHaveAttribute('role', 'status')
  })

  it('tells an empty server from a filter that matched nothing', () => {
    list({ rows: [], model: { total: 0 } })
    expect(screen.getByText('no runs yet')).toBeInTheDocument()

    list({ rows: [], model: { total: 12 } })
    expect(screen.getByText('no runs match the filter')).toBeInTheDocument()
  })

  describe('below the breakpoint', () => {
    beforeEach(() => {
      narrowViewport()
    })

    afterEach(() => {
      wideViewport()
    })

    it('draws each row as two lines: title and pill over the four facts', () => {
      list({
        rows: [
          row({
            title: 'rebuild run detail as a web pane set',
            current_nodes: ['review'],
          }),
        ],
      })

      const [only] = rows()
      expect(only).toHaveAttribute('data-narrow')
      expect(within(only!).getByTestId('narrow-title')).toHaveTextContent(
        'rebuild run detail as a web pane set',
      )
      expect(within(only!).getByText('running')).toBeInTheDocument()
      const meta = within(only!).getByTestId('narrow-meta')
      expect(meta).toHaveTextContent('01JD5XAB')
      expect(meta).toHaveTextContent('feature_build')
      expect(meta).toHaveTextContent('review')
      expect(meta).toHaveTextContent('4m')
    })

    it('calls an untitled run by its id, which the grid leaves to the RUN column', () => {
      list({ rows: [row({ title: '' })] })

      expect(screen.getByTestId('narrow-title')).toHaveTextContent('01JD5XAB')
    })

    it('keeps the ⚠ beside the node, and the whole id in the title attribute', () => {
      list({
        rows: [
          row({ id: 'A', current_nodes: ['review'], pending_requests: 2 }),
          row({ id: 'B', current_nodes: ['qa'], pending_requests: 0 }),
        ],
      })

      expect(within(rows()[0]!).getByTestId('narrow-meta')).toHaveTextContent('⚠')
      expect(within(rows()[1]!).getByTestId('narrow-meta')).not.toHaveTextContent('⚠')
      expect(screen.getByTitle('2 waiting on you')).toBeInTheDocument()
      expect(rows()[0]).toHaveAttribute('title', 'A')
    })

    it('selects on a tap exactly as the grid does on a click', async () => {
      const onSelect = vi.fn()
      list({ rows: [row({ id: 'A' }), row({ id: 'B' })], onSelect })

      await userEvent.click(rows()[1]!)
      expect(onSelect).toHaveBeenCalledWith('B')
      expect(rows()[1]).toHaveAttribute('aria-selected', 'false')
    })

    it('keeps `n shown` in the footer strip', () => {
      list({ rows: [row(), row({ id: 'B' })] })

      expect(screen.getByTestId('rows-shown')).toHaveTextContent('2 shown')
    })
  })
})

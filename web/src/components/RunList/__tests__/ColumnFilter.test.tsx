import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'

import type { RunSummary } from '../../../api/gen/types.gen'
import { keyboardOwned } from '../../../keys'
import { EMPTY_RUN_FILTER, NO_NODE_FILTER, useUi } from '../../../store/ui'
import { ColumnHeading } from '../ColumnFilter'
import { COLUMNS, toLocalInput, type FilterKey } from '../filters'
import { toRow, type RunListModel } from '../useRunList'

const NOW = Date.parse('2026-09-26T12:00:00')

function summary(over: Partial<RunSummary> = {}): RunSummary {
  return {
    id: '01K5AAAA',
    workflow: 'feature_build',
    title: 'rebuild run detail',
    status: 'completed',
    position: 1,
    created: new Date(NOW - 7_200_000).toISOString(),
    updated: new Date(NOW - 3_600_000).toISOString(),
    ...over,
  }
}

const RUNS = [
  summary({ id: 'A', status: 'running', current_nodes: ['review'] }),
  summary({ id: 'B', status: 'failed' }),
]

function model(): RunListModel {
  return {
    rows: RUNS.map((run) => toRow(run, NOW)),
    runs: RUNS,
    now: NOW,
    total: RUNS.length,
    active: 1,
    isPending: false,
    isError: false,
  }
}

function heading(key: FilterKey, narrow = false) {
  const column = COLUMNS.find((each) => each.key === key)!
  return render(<ColumnHeading column={column} model={model()} narrow={narrow} />)
}

async function open(name: string) {
  await userEvent.click(screen.getByRole('button', { name: `filter ${name}` }))
  return screen.getByRole('dialog', { name: `filter ${name}` })
}

describe('ColumnHeading', () => {
  beforeEach(() => {
    useUi.setState({ runFilter: EMPTY_RUN_FILTER })
  })

  it('opens a popover naming the column and how it matches', async () => {
    heading('status')

    const panel = await open('status')
    expect(panel).toHaveTextContent('FILTER · STATUS')
    expect(panel).toHaveTextContent('any of')
    expect(within(panel).getByTestId('filter-tally')).toHaveTextContent('2 / 2 runs')
  })

  it('owns the keyboard while it is open', async () => {
    heading('status')
    expect(keyboardOwned()).toBe(false)

    await open('status')
    expect(keyboardOwned()).toBe(true)

    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(keyboardOwned()).toBe(false)
  })

  it('writes RUN as text the id contains, and closes on ⏎', async () => {
    heading('id')

    const panel = await open('run')
    const box = within(panel).getByRole('textbox', { name: 'run contains' })
    expect(box).toHaveFocus()
    await userEvent.type(box, '01k5{Enter}')

    expect(useUi.getState().runFilter.id).toBe('01k5')
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('checks STATUS choices on and off, with faceted counts', async () => {
    heading('status')

    const panel = await open('status')
    const running = within(panel).getByRole('checkbox', { name: /running/ })
    expect(running).toHaveTextContent('1')
    expect(within(panel).getByRole('checkbox', { name: /paused/ })).toHaveTextContent('0')

    await userEvent.click(running)
    expect(useUi.getState().runFilter.statuses).toEqual(['running'])
    expect(running).toHaveAttribute('aria-checked', 'true')

    await userEvent.click(running)
    expect(useUi.getState().runFilter.statuses).toEqual([])
  })

  it('badges a choice column with how many choices are on', () => {
    useUi.setState({ runFilter: { ...EMPTY_RUN_FILTER, nodes: ['review', NO_NODE_FILTER] } })
    heading('node')

    const funnel = screen.getByRole('button', { name: 'filter node' })
    expect(funnel).toHaveTextContent('2')
    expect(funnel).toHaveAttribute('data-shown', 'true')
    expect(screen.getByText('NODE')).toHaveClass('underline')
  })

  it('offers `(none)` for a run in no node', async () => {
    heading('node')

    const panel = await open('node')
    await userEvent.click(within(panel).getByRole('checkbox', { name: /\(none\)/ }))
    expect(useUi.getState().runFilter.nodes).toEqual([NO_NODE_FILTER])
  })

  it('keeps AGE as a rolling window or a fixed range, never both', async () => {
    heading('age')

    const panel = await open('age')
    const preset = within(panel).getByRole('button', { name: 'last 24h' })
    await userEvent.click(preset)
    expect(useUi.getState().runFilter.within).toBe(86_400_000)
    expect(preset).toHaveAttribute('aria-pressed', 'true')

    const from = within(panel).getByLabelText('created from')
    expect(from).toHaveAttribute('max', toLocalInput(NOW))
    fireEvent.change(from, { target: { value: '2026-09-25T08:00' } })
    expect(useUi.getState().runFilter).toMatchObject({
      within: null,
      after: '2026-09-25T08:00',
    })

    await userEvent.click(within(panel).getByRole('button', { name: 'last 1h' }))
    expect(useUi.getState().runFilter).toMatchObject({
      within: 3_600_000,
      after: '',
      before: '',
    })
  })

  it('clears only its own column', async () => {
    useUi.setState({
      runFilter: { ...EMPTY_RUN_FILTER, statuses: ['failed'], title: 'keep me' },
    })
    heading('status')

    const panel = await open('status')
    await userEvent.click(within(panel).getByRole('button', { name: 'clear' }))
    expect(useUi.getState().runFilter).toEqual({ ...EMPTY_RUN_FILTER, title: 'keep me' })
  })

  it('closes on `done`', async () => {
    heading('title')

    const panel = await open('title')
    await userEvent.click(within(panel).getByRole('button', { name: 'done' }))
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('draws WORKFLOW as a plain heading', () => {
    heading('workflow')

    expect(screen.getByText('WORKFLOW')).toBeInTheDocument()
    expect(screen.queryByRole('button')).toBeNull()
  })

  it('always shows the funnel below the breakpoint', () => {
    heading('title', true)

    const funnel = screen.getByRole('button', { name: 'filter title' })
    expect(funnel).toHaveClass('min-h-[24px]')
    expect(funnel).not.toHaveClass('opacity-0')
  })
})

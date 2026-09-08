import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { RunSummary } from '../../api/gen/types.gen'
import { usePrefs } from '../../store/prefs'
import { PaneBar } from '../PaneBar'
import type { Pane, PaneModel } from '../usePanes'
import { panel } from './fixtures'

const RUN: RunSummary = {
  id: 'run-gamedev',
  workflow: 'gamedev',
  title: 'squirrels vs chipmunks',
  status: 'running',
  position: 1,
  created: '2026-09-08T08:00:00Z',
  updated: '2026-09-08T08:30:00Z',
}

function pane(name: string, builtin: boolean): Pane {
  return {
    id: `${builtin ? '_builtin' : 'gamedev'}:${name}`,
    workflow: builtin ? '_builtin' : 'gamedev',
    name,
    builtin,
    panel: panel({ name }),
  }
}

const PANES: Pane[] = [
  pane('overview', true),
  pane('log', true),
  pane('words', false),
]

function model(over: Partial<PaneModel> = {}): PaneModel {
  const panes = over.panes ?? PANES
  const index = over.index ?? 0
  return {
    panes,
    runId: RUN.id,
    index,
    current: panes[index],
    label: `${panes[index]?.name.toUpperCase() ?? '—'} (${String(index + 1)}/${String(panes.length)})`,
    run: RUN,
    isPending: false,
    prev: vi.fn(),
    next: vi.fn(),
    jump: vi.fn(),
    ...over,
  }
}

function dots() {
  return within(screen.getByRole('radiogroup', { name: 'panes' })).getAllByRole('radio')
}

describe('PaneBar', () => {
  beforeEach(() => {
    usePrefs.setState({ listCollapsed: false })
  })

  it('draws the mock’s ◀ PANE (i/n) ▶', () => {
    render(<PaneBar panes={model({ index: 1 })} />)

    expect(screen.getByTestId('pane-label')).toHaveTextContent('LOG (2/3)')
  })

  it('cycles from the arrows', async () => {
    const panes = model()
    render(<PaneBar panes={panes} />)

    await userEvent.click(screen.getByRole('button', { name: 'next pane' }))
    expect(panes.next).toHaveBeenCalledOnce()

    await userEvent.click(screen.getByRole('button', { name: 'previous pane' }))
    expect(panes.prev).toHaveBeenCalledOnce()
  })

  it('gives one dot to each pane, the current one checked', () => {
    render(<PaneBar panes={model({ index: 2 })} />)

    const bars = dots()
    expect(bars).toHaveLength(3)
    expect(bars[2]).toBeChecked()
    expect(bars[0]).not.toBeChecked()
  })

  it('jumps from a dot', async () => {
    const panes = model()
    render(<PaneBar panes={panes} />)

    await userEvent.click(dots()[2]!)
    expect(panes.jump).toHaveBeenCalledWith(2)
  })

  it('colours the dots accent / accent-800 / neutral-800', () => {
    render(<PaneBar panes={model({ index: 0 })} />)

    const [current, builtin, plugin] = dots()
    expect(current).toHaveClass('bg-[var(--color-accent)]')
    expect(builtin).toHaveClass('bg-[var(--color-neutral-800)]')
    expect(plugin).toHaveClass('bg-[var(--color-accent-800)]')
  })

  it('shows the run and its status pill', () => {
    render(<PaneBar panes={model()} />)

    expect(screen.getByTestId('selected-run')).toHaveTextContent(RUN.id)
    expect(screen.getByText('running')).toBeInTheDocument()
  })

  it('holds the pill back until the run row is known', () => {
    render(<PaneBar panes={model({ run: undefined })} />)

    expect(screen.getByTestId('selected-run')).toHaveTextContent(RUN.id)
    expect(screen.queryByText('running')).toBeNull()
  })

  it('shows nothing about a run when none is selected', () => {
    render(<PaneBar panes={model({ runId: undefined, run: undefined })} />)

    expect(screen.queryByTestId('selected-run')).toBeNull()
  })

  it('disables the arrows and draws no dots with nothing to cycle', () => {
    render(<PaneBar panes={model({ panes: [], index: 0, current: undefined })} />)

    expect(screen.getByRole('button', { name: 'previous pane' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'next pane' })).toBeDisabled()
    expect(
      within(screen.getByRole('radiogroup', { name: 'panes' })).queryAllByRole('radio'),
    ).toHaveLength(0)
  })

  it('collapses the run list, and drops the toggle once it is collapsed', async () => {
    const { rerender } = render(<PaneBar panes={model()} />)

    await userEvent.click(screen.getByRole('button', { name: 'hide run list' }))
    expect(usePrefs.getState().listCollapsed).toBe(true)

    rerender(<PaneBar panes={model()} />)
    expect(screen.queryByRole('button', { name: 'hide run list' })).toBeNull()
  })
})

import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createAppQueryClient } from '../../api/client'
import type { PaneModel } from '../../panes/usePanes'
import { usePrefs } from '../../store/prefs'
import { useUi } from '../../store/ui'
import { Detail } from '../Detail'

/** A pane model with nothing in it, which the shell must still draw. */
function model(over: Partial<PaneModel> = {}): PaneModel {
  return {
    panes: [],
    runId: undefined,
    index: 0,
    current: undefined,
    label: '—',
    run: undefined,
    isPending: false,
    prev: vi.fn(),
    next: vi.fn(),
    jump: vi.fn(),
    ...over,
  }
}

describe('Detail', () => {
  beforeEach(() => {
    useUi.setState({ focus: 'list' })
    usePrefs.setState({ listCollapsed: false })
  })

  it('shows no run when none is selected', () => {
    render(<Detail panes={model()} />)

    expect(screen.queryByTestId('selected-run')).toBeNull()
    expect(screen.getByRole('status')).toHaveTextContent('no run selected')
  })

  it('shows the run from ?run=', () => {
    render(<Detail panes={model({ runId: '01JD5X' })} />)

    expect(screen.getByTestId('selected-run')).toHaveTextContent('01JD5X')
  })

  it('leaves the cycle controls disabled while there are no panes', () => {
    render(<Detail panes={model()} />)

    expect(screen.getByRole('button', { name: 'previous pane' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'next pane' })).toBeDisabled()
  })

  it('says the manifest is still outstanding rather than that there are none', () => {
    render(<Detail panes={model({ isPending: true })} />)

    expect(screen.getByRole('status')).toHaveTextContent('loading panes…')
  })

  it('stops saying there are none once the cycle has a pane', () => {
    const pane = {
      id: '_builtin:agent',
      workflow: '_builtin',
      name: 'agent',
      builtin: true,
      panel: {
        name: 'agent',
        slot: 'run' as const,
        scope: 'run' as const,
        placement: 'pane' as const,
        kind: 'custom' as const,
        element: 'ath-agent-stream',
      },
    }
    render(
      // `PaneRenderer` reads its panel's `source` through the query
      // cache, so the body needs one even for a pane that fetches
      // nothing (T062a).
      <QueryClientProvider client={createAppQueryClient()}>
        <Detail panes={model({ runId: '01JD5X', panes: [pane], current: pane })} />
      </QueryClientProvider>,
    )

    // What the pane draws is `PaneRenderer`'s — the agent stream says
    // `loading the run…` here, and that status is the pane's own — so
    // what the host owns is that the body stops standing in for a
    // missing pane with one of its own three lines.
    expect(screen.queryByText('this run has no panes')).toBeNull()
    expect(screen.queryByText('loading panes…')).toBeNull()
    expect(screen.queryByText('no run selected')).toBeNull()
    expect(screen.getByTestId('pane-body')).toHaveAttribute('data-pane', '_builtin:agent')
    expect(screen.getByTestId('pane-renderer')).toHaveAttribute('data-kind', 'custom')
  })

  it('takes focus when it is clicked', async () => {
    render(<Detail panes={model()} />)

    await userEvent.click(screen.getByRole('region', { name: 'detail' }))
    expect(useUi.getState().focus).toBe('detail')
  })

  it('collapses the run list from the pane bar', async () => {
    render(<Detail panes={model()} />)

    await userEvent.click(screen.getByRole('button', { name: 'hide run list' }))
    expect(usePrefs.getState().listCollapsed).toBe(true)
  })

  it('drops the collapse toggle once the list is collapsed', () => {
    usePrefs.setState({ listCollapsed: true })
    render(<Detail panes={model()} />)

    // The rail's own `❯` is the way back (`../Splitter`), so the bar
    // never carries a second control for the same thing.
    expect(screen.queryByRole('button', { name: 'hide run list' })).toBeNull()
  })
})

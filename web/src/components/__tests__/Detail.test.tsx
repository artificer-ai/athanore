import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

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
      id: '_builtin:overview',
      workflow: '_builtin',
      name: 'overview',
      builtin: true,
      panel: {
        name: 'overview',
        slot: 'run' as const,
        scope: 'run' as const,
        placement: 'pane' as const,
        kind: 'dashboard' as const,
      },
    }
    render(<Detail panes={model({ runId: '01JD5X', panes: [pane], current: pane })} />)

    // What the pane draws is `PaneRenderer`'s (T062a); what the host
    // owns is that the body stops standing in for a missing pane.
    expect(screen.queryByRole('status')).toBeNull()
    expect(screen.getByTestId('pane-body')).toHaveAttribute(
      'data-pane',
      '_builtin:overview',
    )
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

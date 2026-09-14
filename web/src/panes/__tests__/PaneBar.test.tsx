import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { RunSummary } from '../../api/gen/types.gen'
import { narrowViewport, wideViewport } from '../../lib/__tests__/fixtures'
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

  describe('above the breakpoint', () => {
    beforeEach(() => {
      wideViewport()
    })

    it('draws only the collapse toggle, no back control: esc clears the selection', () => {
      // Wide, `esc` is the one route to deselection (D209); a pointer
      // control beside the collapse toggle read as one confused control.
      usePrefs.setState({ listCollapsed: false })
      render(<PaneBar panes={model()} onBack={vi.fn()} />)

      expect(
        screen.queryByRole('button', { name: 'clear the selected run' }),
      ).toBeNull()
      expect(screen.getByRole('button', { name: 'hide run list' })).toBeInTheDocument()
    })

    it('draws no back control when nothing is selected either', () => {
      render(<PaneBar panes={model({ run: undefined, runId: undefined })} onBack={vi.fn()} />)

      expect(
        screen.queryByRole('button', { name: 'clear the selected run' }),
      ).toBeNull()
    })
  })

  describe('below the breakpoint', () => {
    beforeEach(() => {
      narrowViewport()
    })

    afterEach(() => {
      wideViewport()
    })

    it('puts a back control in the left slot instead of the collapse toggle', async () => {
      const onBack = vi.fn()
      render(<PaneBar panes={model()} onBack={onBack} />)

      expect(screen.queryByRole('button', { name: 'hide run list' })).toBeNull()
      await userEvent.click(screen.getByRole('button', { name: 'back to runs' }))
      expect(onBack).toHaveBeenCalledOnce()
      // Nothing about the desktop geometry is touched on the way (D194).
      expect(usePrefs.getState().listCollapsed).toBe(false)
    })

    it('draws the back control even where the list was left collapsed', () => {
      usePrefs.setState({ listCollapsed: true })
      render(<PaneBar panes={model()} onBack={vi.fn()} />)

      expect(screen.getByRole('button', { name: 'back to runs' })).toBeInTheDocument()
    })

    it('draws no back control in a shell that passes no handler', () => {
      // A control that does nothing when clicked is worse than no
      // control: the operator presses it, the selection stays, and the
      // conclusion is that back is broken rather than absent.
      render(<PaneBar panes={model()} />)

      expect(screen.queryByRole('button', { name: 'back to runs' })).toBeNull()
    })

    it('keeps the arrows and the dots: they are the touch route round the cycle', async () => {
      const panes = model()
      render(<PaneBar panes={panes} onBack={vi.fn()} />)

      await userEvent.click(screen.getByRole('button', { name: 'next pane' }))
      expect(panes.next).toHaveBeenCalledOnce()
      await userEvent.click(dots()[2]!)
      expect(panes.jump).toHaveBeenCalledWith(2)
    })

    describe('over the global screen', () => {
      /**
       * The global cycle: `panes.run` unset — the model is the global
       * view's — and `leave` given (D216). The screen sits beside the
       * list (D218), so its `←` reads as the detail's does.
       */
      const GLOBAL: Pane[] = [pane('inbox', true), pane('crontab', false)]

      function global() {
        return model({ panes: GLOBAL, runId: undefined, run: undefined })
      }

      it('draws `←` back to runs, and it clears the screen — not the selection', async () => {
        const onLeave = vi.fn()
        const onBack = vi.fn()
        render(<PaneBar panes={global()} onBack={onBack} leave={onLeave} />)

        const back = screen.getByRole('button', { name: 'back to runs' })
        expect(back).toHaveClass('max-md:min-h-[24px]')
        expect(back).toHaveAttribute('title', 'back to runs (esc)')
        await userEvent.click(back)
        expect(onLeave).toHaveBeenCalledOnce()
        expect(onBack).not.toHaveBeenCalled()
      })

      it('draws one control in the left slot, and nothing about a run on the right', () => {
        // Neither the selection's back control nor the collapse toggle;
        // the right slot is gated on `runId`, as the desktop's global
        // view is. The one control is the screen's own `←`, labelled as
        // the detail's is because both go to the list (D218).
        render(<PaneBar panes={global()} onBack={vi.fn()} leave={vi.fn()} />)

        expect(screen.getAllByRole('button', { name: /back|clear|hide/ })).toHaveLength(1)
        expect(screen.getByRole('button', { name: 'back to runs' })).toBeInTheDocument()
        expect(screen.queryByRole('button', { name: 'hide run list' })).toBeNull()
        expect(
          screen.queryByRole('button', { name: 'clear the selected run' }),
        ).toBeNull()
        expect(screen.queryByTestId('selected-run')).toBeNull()
        expect(screen.queryByText('run')).toBeNull()
        // The same mapping as everywhere: the inbox is a builtin, the
        // plugin's global pane is a plugin's (D216 (2)).
        expect(dots()[0]).toHaveAttribute('data-builtin', 'true')
        expect(dots()[1]).toHaveClass('bg-[var(--color-accent-800)]')
      })
    })
  })
})

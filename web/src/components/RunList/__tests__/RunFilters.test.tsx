import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'

import { ALL_WORKFLOWS, DEFAULT_RUN_FILTER, RUN_STATUSES, useUi } from '../../../store/ui'
import { RunFilters } from '../RunFilters'

const WORKFLOWS = ['claude_acp', 'feature_build', 'gamedev']

/** The status group: Radix draws a multiple `ToggleGroup` as a toolbar. */
function statusGroup() {
  return screen.getByRole('toolbar', { name: 'filter by status' })
}

function statusChip(status: string) {
  return within(statusGroup()).getByRole('button', { name: status })
}

function allStatuses() {
  return screen.getByRole('button', { name: 'all statuses' })
}

describe('RunFilters', () => {
  beforeEach(() => {
    useUi.setState({
      runFilter: { ...DEFAULT_RUN_FILTER, statuses: [...DEFAULT_RUN_FILTER.statuses] },
    })
  })

  it('offers `all` and one chip per workflow, in that order', () => {
    render(<RunFilters workflows={WORKFLOWS} />)

    const chips = screen.getAllByRole('radio').map((chip) => chip.textContent)
    expect(chips).toEqual(['all', ...WORKFLOWS])
  })

  it('tints the chip that is on, and only that one', () => {
    useUi.setState({ runFilter: { ...DEFAULT_RUN_FILTER, workflow: 'gamedev' } })
    render(<RunFilters workflows={WORKFLOWS} />)

    expect(screen.getByRole('radio', { name: 'gamedev' })).toHaveAttribute(
      'data-state',
      'on',
    )
    expect(screen.getByRole('radio', { name: 'all' })).toHaveAttribute(
      'data-state',
      'off',
    )
  })

  it('writes the chip that was clicked', async () => {
    render(<RunFilters workflows={WORKFLOWS} />)

    await userEvent.click(screen.getByRole('radio', { name: 'feature_build' }))
    expect(useUi.getState().runFilter.workflow).toBe('feature_build')
  })

  it('falls back to `all` when the chip that was on is switched off', async () => {
    useUi.setState({ runFilter: { ...DEFAULT_RUN_FILTER, workflow: 'gamedev' } })
    render(<RunFilters workflows={WORKFLOWS} />)

    await userEvent.click(screen.getByRole('radio', { name: 'gamedev' }))
    expect(useUi.getState().runFilter.workflow).toBe(ALL_WORKFLOWS)
  })

  it('writes what is typed into the `/` input', async () => {
    render(<RunFilters workflows={WORKFLOWS} />)

    await userEvent.type(screen.getByRole('textbox', { name: 'filter runs' }), 'snakes')
    expect(useUi.getState().runFilter.query).toBe('snakes')
  })

  it('offers one status chip per status, in 03’s order, after `all statuses`', () => {
    render(<RunFilters workflows={WORKFLOWS} />)

    const chips = within(statusGroup())
      .getAllByRole('button')
      .map((chip) => chip.textContent)
    expect(chips).toEqual([...RUN_STATUSES])
    expect(
      allStatuses().compareDocumentPosition(statusGroup()) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()
  })

  it('starts with completed and cancelled off, and `all statuses` off with them', () => {
    render(<RunFilters workflows={WORKFLOWS} />)

    for (const status of ['queued', 'running', 'paused', 'failed']) {
      expect(statusChip(status)).toHaveAttribute('aria-pressed', 'true')
      expect(statusChip(status)).toHaveAttribute('data-state', 'on')
    }
    for (const status of ['completed', 'cancelled']) {
      expect(statusChip(status)).toHaveAttribute('aria-pressed', 'false')
      expect(statusChip(status)).toHaveAttribute('data-state', 'off')
    }
    expect(allStatuses()).toHaveAttribute('aria-pressed', 'false')
  })

  it('`all statuses` turns every status on, and is on only then', async () => {
    render(<RunFilters workflows={WORKFLOWS} />)

    await userEvent.click(allStatuses())
    expect(useUi.getState().runFilter.statuses).toEqual([...RUN_STATUSES])
    expect(allStatuses()).toHaveAttribute('aria-pressed', 'true')
    expect(statusChip('completed')).toHaveAttribute('aria-pressed', 'true')

    // One-way: pressing it again changes nothing.
    await userEvent.click(allStatuses())
    expect(useUi.getState().runFilter.statuses).toEqual([...RUN_STATUSES])
    expect(allStatuses()).toHaveAttribute('aria-pressed', 'true')

    // And one status off takes it off again.
    await userEvent.click(statusChip('cancelled'))
    expect(allStatuses()).toHaveAttribute('aria-pressed', 'false')
  })

  it('toggles a status chip on and off, in chip order', async () => {
    render(<RunFilters workflows={WORKFLOWS} />)

    await userEvent.click(statusChip('completed'))
    expect(useUi.getState().runFilter.statuses).toEqual([
      'queued',
      'running',
      'paused',
      'completed',
      'failed',
    ])
    expect(statusChip('completed')).toHaveAttribute('data-state', 'on')

    await userEvent.click(statusChip('running'))
    expect(useUi.getState().runFilter.statuses).toEqual([
      'queued',
      'paused',
      'completed',
      'failed',
    ])
    expect(statusChip('running')).toHaveAttribute('data-state', 'off')
  })

  it('lets every status be off: there is no floor', async () => {
    render(<RunFilters workflows={WORKFLOWS} />)

    for (const status of ['queued', 'running', 'paused', 'failed']) {
      await userEvent.click(statusChip(status))
    }
    expect(useUi.getState().runFilter.statuses).toEqual([])
    for (const status of RUN_STATUSES) {
      expect(statusChip(status)).toHaveAttribute('aria-pressed', 'false')
    }
  })

  it('reaches the status chips by tab and toggles them with space and enter', async () => {
    const user = userEvent.setup()
    render(<RunFilters workflows={WORKFLOWS} />)

    // Tab from the document until focus is inside the status toolbar:
    // the roving group lands on one chip, and `→` moves along it.
    const group = statusGroup()
    for (let i = 0; i < 10 && !group.contains(document.activeElement); i += 1) {
      await user.tab()
    }
    expect(group.contains(document.activeElement)).toBe(true)
    for (let i = 0; i < RUN_STATUSES.length; i += 1) {
      if (document.activeElement === statusChip('completed')) break
      await user.keyboard('{ArrowRight}')
    }
    expect(document.activeElement).toBe(statusChip('completed'))

    await user.keyboard(' ')
    expect(useUi.getState().runFilter.statuses).toContain('completed')

    await user.keyboard('{Enter}')
    expect(useUi.getState().runFilter.statuses).not.toContain('completed')
  })

  it('keeps the workflow `all` and the status `all` two controls', () => {
    render(<RunFilters workflows={WORKFLOWS} />)

    const workflowAll = screen.getByRole('radio', { name: 'all' })
    expect(workflowAll).toBeInTheDocument()
    expect(allStatuses()).toBeInTheDocument()
    expect(workflowAll).not.toBe(allStatuses())
  })
})

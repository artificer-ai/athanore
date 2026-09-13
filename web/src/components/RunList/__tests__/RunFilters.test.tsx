import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'

import { ALL_WORKFLOWS, useUi } from '../../../store/ui'
import { RunFilters } from '../RunFilters'

const WORKFLOWS = ['claude_acp', 'feature_build', 'gamedev']

describe('RunFilters', () => {
  beforeEach(() => {
    useUi.setState({ runFilter: { workflow: ALL_WORKFLOWS, query: '' } })
  })

  it('offers `all` and one chip per workflow, in that order', () => {
    render(<RunFilters workflows={WORKFLOWS} />)

    const chips = screen.getAllByRole('radio').map((chip) => chip.textContent)
    expect(chips).toEqual(['all', ...WORKFLOWS])
  })

  it('tints the chip that is on, and only that one', () => {
    useUi.setState({ runFilter: { workflow: 'gamedev', query: '' } })
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
    useUi.setState({ runFilter: { workflow: 'gamedev', query: '' } })
    render(<RunFilters workflows={WORKFLOWS} />)

    await userEvent.click(screen.getByRole('radio', { name: 'gamedev' }))
    expect(useUi.getState().runFilter.workflow).toBe(ALL_WORKFLOWS)
  })

  it('writes what is typed into the `/` input', async () => {
    render(<RunFilters workflows={WORKFLOWS} />)

    await userEvent.type(screen.getByRole('textbox', { name: 'filter runs' }), 'snakes')
    expect(useUi.getState().runFilter.query).toBe('snakes')
  })
})

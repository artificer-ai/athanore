import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'

import { usePrefs } from '../../store/prefs'
import { useUi } from '../../store/ui'
import { Detail } from '../Detail'

describe('Detail', () => {
  beforeEach(() => {
    useUi.setState({ focus: 'list' })
    usePrefs.setState({ listCollapsed: false })
  })

  it('shows no run when none is selected', () => {
    render(<Detail search={{}} />)

    expect(screen.queryByTestId('selected-run')).toBeNull()
  })

  it('shows the run from ?run=', () => {
    render(<Detail search={{ run: '01JD5X' }} />)

    expect(screen.getByTestId('selected-run')).toHaveTextContent('01JD5X')
  })

  it('leaves the cycle controls disabled while there are no panes', () => {
    render(<Detail search={{}} />)

    expect(screen.getByRole('button', { name: 'previous pane' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'next pane' })).toBeDisabled()
  })

  it('takes focus when it is clicked', async () => {
    render(<Detail search={{}} />)

    await userEvent.click(screen.getByRole('region', { name: 'detail' }))
    expect(useUi.getState().focus).toBe('detail')
  })

  it('collapses the run list from the pane bar', async () => {
    render(<Detail search={{}} />)

    await userEvent.click(screen.getByRole('button', { name: 'hide run list' }))
    expect(usePrefs.getState().listCollapsed).toBe(true)
  })

  it('drops the collapse toggle once the list is collapsed', () => {
    usePrefs.setState({ listCollapsed: true })
    render(<Detail search={{}} />)

    // The rail's own `❯` is the way back (`../Splitter`), so the bar
    // never carries a second control for the same thing.
    expect(screen.queryByRole('button', { name: 'hide run list' })).toBeNull()
  })
})

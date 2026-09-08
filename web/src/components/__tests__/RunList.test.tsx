import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'

import { useUi } from '../../store/ui'
import { RunList } from '../RunList'

describe('RunList', () => {
  beforeEach(() => {
    useUi.setState({ focus: 'list' })
  })

  it('renders the six columns of the mock and the footer strip', () => {
    render(<RunList count={0} />)

    for (const heading of ['RUN', 'WORKFLOW', 'TITLE', 'STATUS', 'NODE', 'AGE']) {
      expect(screen.getByText(heading)).toBeInTheDocument()
    }
    expect(screen.getByTestId('rows-shown')).toHaveTextContent('0 shown')
    expect(screen.getByText('↑↓ select')).toBeInTheDocument()
    expect(screen.getByText('⏎ focus detail')).toBeInTheDocument()
  })

  it('reports the count it is given', () => {
    render(<RunList count={34} />)
    expect(screen.getByTestId('rows-shown')).toHaveTextContent('34 shown')
  })

  it('takes focus when it is clicked', async () => {
    useUi.setState({ focus: 'detail' })
    render(<RunList count={0} />)

    await userEvent.click(screen.getByRole('region', { name: 'runs' }))
    expect(useUi.getState().focus).toBe('list')
  })
})

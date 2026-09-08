import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { Header } from '../Header'

describe('Header', () => {
  it('shows the brand mark and the version vite injected', () => {
    render(<Header />)

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('▚ ATHANORE')
    // `__APP_VERSION__` is pyproject.toml's `[project] version`; asserting
    // the literal would pin the test to a release.
    expect(screen.getByText(`v${__APP_VERSION__}`)).toBeInTheDocument()
    expect(__APP_VERSION__).toMatch(/^\d+\.\d+\.\d+/)
  })

  it('omits the counts rather than zero-filling them', () => {
    render(<Header />)

    // 02 §Real data only: unknown is omitted, never estimated.
    expect(screen.getByTestId('run-count')).toHaveTextContent('— runs')
    expect(screen.getByTestId('active-count')).toHaveTextContent('— active')
  })

  it('does not pulse the active dot while nothing is in progress', () => {
    const { container } = render(<Header />)

    expect(container.querySelector('[data-active="true"]')).toBeNull()
  })
})

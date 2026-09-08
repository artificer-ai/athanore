import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { useUi } from '../../store/ui'
import { Header } from '../Header'

describe('Header', () => {
  afterEach(() => {
    useUi.setState({ feed: { status: 'reconnecting', retryAt: null } })
  })

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

  it('greys the counts out when the server is down', () => {
    useUi.setState({ feed: { status: 'down', retryAt: null } })

    render(<Header />)

    // The numbers stay on screen — they are the last the server gave —
    // and greying them is how the strip says nobody is standing behind
    // them any more (10 §Realtime and caching).
    expect(screen.getByTestId('header-counts')).toHaveAttribute('data-down', 'true')
    expect(screen.getByTestId('run-count')).toHaveTextContent('— runs')
  })

  it('leaves them alone while it is hearing from the server', () => {
    useUi.setState({ feed: { status: 'open', retryAt: null } })

    render(<Header />)

    expect(screen.getByTestId('header-counts')).toHaveAttribute('data-down', 'false')
  })
})

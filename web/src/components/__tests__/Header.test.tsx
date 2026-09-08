import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { ALL_WORKFLOWS, useUi } from '../../store/ui'
import type { RunListModel } from '../RunList'
import { Header } from '../Header'

/** A model the server has not answered for yet: what a fresh page holds. */
const UNANSWERED: RunListModel = {
  rows: [],
  total: null,
  active: null,
  workflows: [],
  isPending: true,
  isError: false,
}

function header(over: Partial<RunListModel> = {}) {
  return render(<Header runs={{ ...UNANSWERED, ...over }} />)
}

describe('Header', () => {
  beforeEach(() => {
    useUi.setState({ runFilter: { workflow: ALL_WORKFLOWS, query: '' } })
  })

  afterEach(() => {
    useUi.setState({ feed: { status: 'reconnecting', retryAt: null } })
  })

  it('shows the brand mark and the version vite injected', () => {
    header()

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('▚ ATHANORE')
    // `__APP_VERSION__` is pyproject.toml's `[project] version`; asserting
    // the literal would pin the test to a release.
    expect(screen.getByText(`v${__APP_VERSION__}`)).toBeInTheDocument()
    expect(__APP_VERSION__).toMatch(/^\d+\.\d+\.\d+/)
  })

  it('omits the counts rather than zero-filling them', () => {
    header()

    // 02 §Real data only: unknown is omitted, never estimated.
    expect(screen.getByTestId('run-count')).toHaveTextContent('— runs')
    expect(screen.getByTestId('active-count')).toHaveTextContent('— active')
  })

  it('reports the counts the run list is drawn from', () => {
    header({ total: 34, active: 2, isPending: false })

    expect(screen.getByTestId('run-count')).toHaveTextContent('34 runs')
    expect(screen.getByTestId('active-count')).toHaveTextContent('2 active')
  })

  it('does not pulse the active dot while nothing is in progress', () => {
    const { container } = header({ total: 34, active: 0, isPending: false })

    expect(container.querySelector('[data-active="true"]')).toBeNull()
  })

  it('pulses the active dot once something is', () => {
    const { container } = header({ total: 34, active: 1, isPending: false })

    expect(container.querySelector('[data-active="true"]')).toHaveClass(
      'data-[active=true]:animate-ath-pulse',
    )
  })

  it('carries the run list’s chips and its `/` input', () => {
    header({ workflows: ['feature_build', 'gamedev'], total: 3, isPending: false })

    expect(screen.getAllByRole('radio').map((chip) => chip.textContent)).toEqual([
      'all',
      'feature_build',
      'gamedev',
    ])
    expect(screen.getByRole('textbox', { name: 'filter runs' })).toBeInTheDocument()
  })

  it('greys the counts out when the server is down', () => {
    useUi.setState({ feed: { status: 'down', retryAt: null } })

    header({ total: 34, active: 1, isPending: false })

    // The numbers stay on screen — they are the last the server gave —
    // and greying them is how the strip says nobody is standing behind
    // them any more (10 §Realtime and caching).
    expect(screen.getByTestId('header-counts')).toHaveAttribute('data-down', 'true')
    expect(screen.getByTestId('run-count')).toHaveTextContent('34 runs')
  })

  it('leaves them alone while it is hearing from the server', () => {
    useUi.setState({ feed: { status: 'open', retryAt: null } })

    header()

    expect(screen.getByTestId('header-counts')).toHaveAttribute('data-down', 'false')
  })
})

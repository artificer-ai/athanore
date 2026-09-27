import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { FONT_SIZES, usePrefs } from '../../store/prefs'
import { EMPTY_RUN_FILTER, useUi } from '../../store/ui'
import type { RunListModel } from '../RunList'
import { Header } from '../Header'

/** A model the server has not answered for yet: what a fresh page holds. */
const UNANSWERED: RunListModel = {
  rows: [],
  runs: [],
  now: 0,
  total: null,
  active: null,
  isPending: true,
  isError: false,
}

/** The strip, and the handlers its two buttons call. */
function header(over: Partial<RunListModel> = {}) {
  const onNewRun = vi.fn()
  const onOpenLibrary = vi.fn()
  return {
    onNewRun,
    onOpenLibrary,
    ...render(
      <Header
        runs={{ ...UNANSWERED, ...over }}
        onNewRun={onNewRun}
        onOpenLibrary={onOpenLibrary}
      />,
    ),
  }
}

describe('Header', () => {
  beforeEach(() => {
    useUi.setState({ runFilter: EMPTY_RUN_FILTER })
    usePrefs.setState({ fontSize: 'default' })
  })

  afterEach(() => {
    useUi.setState({ feed: { status: 'reconnecting', retryAt: null } })
  })

  it('shows the brand mark and the version vite injected', () => {
    header()

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('┤ ATHANORE ├')
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

  it('carries no run filter of its own: the list’s headings are the filter', () => {
    header({ total: 3, isPending: false })

    expect(screen.queryByRole('textbox')).toBeNull()
    expect(screen.queryByRole('radio')).toBeNull()
  })

  it('says on `workflows` how many workflows the library has marked', () => {
    useUi.setState({ runFilter: { ...EMPTY_RUN_FILTER, workflows: ['a', 'b'] } })
    header({ total: 3, isPending: false })

    const button = screen.getByRole('button', { name: 'workflows · 2' })
    expect(button).toHaveAttribute('data-filtered', 'true')
    expect(button).toHaveAttribute(
      'title',
      '2 workflow filters on — change them in the library (w)',
    )
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

  it('opens the new run overlay from the mock’s ＋ new run button', async () => {
    const user = userEvent.setup()
    const { onNewRun } = header()

    // The `＋` is decorative and `aria-hidden`, so the accessible name
    // is the two words a screen reader should read.
    await user.click(screen.getByRole('button', { name: 'new run' }))

    expect(onNewRun).toHaveBeenCalledTimes(1)
  })

  it('opens the workflow library from the mock’s workflows button', async () => {
    const user = userEvent.setup()
    const { onOpenLibrary } = header()

    await user.click(screen.getByRole('button', { name: 'workflows' }))

    expect(onOpenLibrary).toHaveBeenCalledTimes(1)
  })

  it('offers the four type-scale steps behind the text-size button', async () => {
    // 21 §Type scale: an icon-only button, so the accessible name is the
    // whole of what a screen reader has to go on (D196).
    const user = userEvent.setup()
    header()

    await user.click(screen.getByRole('button', { name: 'text size' }))

    const group = screen.getByRole('radiogroup', { name: 'text size' })
    const rows = within(group).getAllByRole('radio')
    expect(rows).toHaveLength(FONT_SIZES.length)
    // The accessible name of each row is its step and nothing else: the
    // dot that marks the current one is `aria-hidden`, because
    // `aria-checked` already says it.
    for (const [index, step] of FONT_SIZES.entries()) {
      expect(rows[index]).toHaveAccessibleName(step)
    }
    // The step in force is marked, and it is the store's.
    expect(within(group).getByRole('radio', { name: 'default' })).toBeChecked()
  })

  it('writes the chosen step to usePrefs and nothing else', async () => {
    const user = userEvent.setup()
    header()

    await user.click(screen.getByRole('button', { name: 'text size' }))
    await user.click(screen.getByRole('radio', { name: 'xlarge' }))

    expect(usePrefs.getState().fontSize).toBe('xlarge')
  })

  it('marks the step the store already holds', async () => {
    const user = userEvent.setup()
    usePrefs.setState({ fontSize: 'small' })
    header()

    await user.click(screen.getByRole('button', { name: 'text size' }))

    expect(screen.getByRole('radio', { name: 'small' })).toBeChecked()
    expect(screen.getByRole('radio', { name: 'default' })).not.toBeChecked()
  })
})

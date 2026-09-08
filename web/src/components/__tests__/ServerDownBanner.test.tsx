import { QueryClient } from '@tanstack/react-query'
import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createAppEventFeed, type EventSourceLike } from '../../realtime/sse'
import { useUi, type Feed } from '../../store/ui'
import { ServerDownBanner, TICK_MS } from '../ServerDownBanner'

/** Put the feed's state where the header and the banner read it. */
function feedIs(feed: Feed) {
  useUi.setState({ feed })
}

describe('ServerDownBanner', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-08T09:00:00Z'))
  })

  afterEach(() => {
    vi.useRealTimers()
    feedIs({ status: 'reconnecting', retryAt: null })
  })

  it('says nothing while the stream is up', () => {
    feedIs({ status: 'open', retryAt: null })

    render(<ServerDownBanner />)

    expect(screen.queryByTestId('server-down-banner')).toBeNull()
  })

  it('says nothing about a connection that is merely coming back', () => {
    // One dropped connection is not news; the feed only reports `down`
    // once a retry has failed too (`realtime/sse.ts`).
    feedIs({ status: 'reconnecting', retryAt: Date.now() + 1000 })

    render(<ServerDownBanner />)

    expect(screen.queryByTestId('server-down-banner')).toBeNull()
  })

  it('shows the reason and the countdown to the next attempt', () => {
    feedIs({ status: 'down', retryAt: Date.now() + 8000 })

    render(<ServerDownBanner />)
    // The clock is read on the tick, never during a render.
    act(() => vi.advanceTimersByTime(TICK_MS))

    expect(screen.getByTestId('server-down-banner')).toHaveTextContent('no server')
    expect(screen.getByTestId('server-down-countdown')).toHaveTextContent(
      'retrying in 8s',
    )
  })

  it('counts down as the attempt approaches', () => {
    feedIs({ status: 'down', retryAt: Date.now() + 8000 })
    render(<ServerDownBanner />)

    // Inside `act`, because the tick is a React state update.
    act(() => vi.advanceTimersByTime(5000))

    expect(screen.getByTestId('server-down-countdown')).toHaveTextContent(
      'retrying in 3s',
    )
  })

  it('says it is trying while an attempt is in flight', () => {
    feedIs({ status: 'down', retryAt: null })

    render(<ServerDownBanner />)
    act(() => vi.advanceTimersByTime(TICK_MS * 4))

    expect(screen.getByTestId('server-down-countdown')).toHaveTextContent(
      'reconnecting…',
    )
  })

  it('reconnects the tab’s feed on the operator’s word', () => {
    const opened: string[] = []
    const feed = createAppEventFeed(new QueryClient(), {
      open: (url): EventSourceLike => {
        opened.push(url)
        return { addEventListener: () => {}, close: () => {} }
      },
    })
    feed.start()
    feedIs({ status: 'down', retryAt: Date.now() + 30000 })
    render(<ServerDownBanner />)

    screen.getByRole('button', { name: 'try now' }).click()

    expect(opened).toHaveLength(2)
    feed.stop()
  })
})

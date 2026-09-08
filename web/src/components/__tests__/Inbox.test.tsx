/**
 * The inbox: every open request across every run, newest first, with the
 * count in its header (`components/Inbox.tsx`,
 * `docs/v1/06-requests.md` §Surfaces, `docs/v1/10-frontend.md` §Panes
 * item 4 and §Attention).
 *
 * Three things worth being strict about:
 *
 * - **the order is the opposite of the run pane's.** The route answers
 *   oldest first (`athanore/store/repos/requests.py`), and the fixture
 *   below is in that order, so an inbox that drew the list as it arrived
 *   fails here.
 * - **the key is `queryKeys.inbox()`.** The panel refetches that key
 *   after it answers and the event feed invalidates it on `request.*`
 *   (10 §Realtime and caching); a query asked with options of its own
 *   would sit in an entry neither of them reaches.
 * - **the notify toggle is the opt-in**, and it asks the browser at the
 *   click rather than on load (10 §Attention).
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createAppQueryClient } from '../../api/client'
import type { RequestView } from '../../api/gen/types.gen'
import { request } from '../../panes/__tests__/fixtures'
import { queryKeys } from '../../realtime/invalidate'
import { usePrefs } from '../../store/prefs'
import { Inbox } from '../Inbox'
import { newestFirst } from '../inbox'

const { toast } = vi.hoisted(() => ({ toast: vi.fn() }))
vi.mock('sonner', () => ({ toast, Toaster: () => null }))

let queryClient: QueryClient

/** Two runs' worth of open questions, oldest first as the route sends. */
const OPEN: RequestView[] = [
  request({
    id: 31,
    run_id: '01JD5XRUNAAAAAAAAAAAAAAA',
    node: 'engineering',
    prompt: 'Which package manager?',
    pending: true,
    created: '2026-09-08T09:00:01Z',
  }),
  request({
    id: 32,
    run_id: '01JD5XRUNBBBBBBBBBBBBBBB',
    node: 'review',
    source: 'agent',
    kind: 'permission',
    mode: 'options',
    prompt: 'permission: run the gate',
    options: [{ option_id: 'allow_once', name: 'Allow once', kind: 'allow_once' }],
    pending: true,
    created: '2026-09-08T09:00:02Z',
  }),
  request({
    id: 33,
    run_id: '01JD5XRUNBBBBBBBBBBBBBBB',
    node: 'review',
    prompt: 'Anything else?',
    pending: true,
    created: '2026-09-08T09:00:02Z',
  }),
]

function stubFetch(body: unknown, status = 200) {
  const urls: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (req: Request) => {
      urls.push(req.url)
      return new Response(JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
  return urls
}

function draw(rows: readonly RequestView[] | null = OPEN) {
  if (rows !== null) queryClient.setQueryData(queryKeys.inbox(), rows)
  return render(
    <QueryClientProvider client={queryClient}>
      <Inbox />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  queryClient = createAppQueryClient()
  queryClient.setDefaultOptions({ queries: { retry: false, staleTime: Infinity } })
  usePrefs.setState({ notifications: false })
  toast.mockClear()
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('the order', () => {
  it('is newest first, by the moment each was opened', () => {
    expect(newestFirst(OPEN).map((row) => row.id)).toEqual([33, 32, 31])
  })

  it('breaks a tie by id, because two can share a clock tick', () => {
    // 32 and 33 were opened in the same second; the later id is later.
    const tied = OPEN.filter((row) => row.id !== 31)
    expect(newestFirst(tied).map((row) => row.id)).toEqual([33, 32])
  })

  it('draws the cards in that order, each naming the run it came from', () => {
    draw()

    const cards = screen.getAllByTestId('request-card')
    expect(cards.map((card) => card.getAttribute('data-request'))).toEqual([
      '33',
      '32',
      '31',
    ])
    expect(within(cards[0]!).getByTestId('request-run')).toHaveTextContent(
      'run 01JD5XRU',
    )
  })
})

describe('the header', () => {
  it('counts what is open', () => {
    draw()
    expect(screen.getByTestId('inbox-count')).toHaveTextContent('⚠ 3 open')
  })

  it('says so when nothing is waiting, rather than showing an empty list', () => {
    draw([])

    expect(screen.getByTestId('inbox-count')).toHaveTextContent('○ none open')
    expect(screen.getByRole('status')).toHaveTextContent('nothing is waiting on you')
  })
})

describe('what it reads', () => {
  it('asks `/api/requests` with no options, so the key is the one the feed refreshes', async () => {
    const urls = stubFetch(OPEN)

    draw(null)

    expect(screen.getByRole('status')).toHaveTextContent('loading the inbox…')
    await waitFor(() => {
      expect(screen.getAllByTestId('request-card')).toHaveLength(3)
    })
    expect(urls).toEqual(['http://localhost:3000/api/requests'])
    expect(queryClient.getQueryData(queryKeys.inbox())).toHaveLength(3)
  })

  it('names its own refusal rather than looking like a quiet machine', async () => {
    stubFetch({ error: 'the store is not available', code: 'not_found' }, 404)

    draw(null)

    const card = await screen.findByTestId('pane-error')
    expect(card).toHaveTextContent('the store is not available')
    expect(card).toHaveTextContent('/api/requests')
  })

  it('answers a request in place, with the same panel the pane draws', () => {
    draw()

    const card = screen
      .getAllByTestId('request-card')
      .find((row) => row.getAttribute('data-request') === '32')
    expect(within(card!).getByTestId('request-panel')).toHaveAttribute(
      'data-mode',
      'options',
    )
  })
})

describe('the notification opt-in', () => {
  it('asks the browser at the click, and only then turns the setting on', async () => {
    const user = userEvent.setup()
    const requestPermission = vi.fn(() => Promise.resolve('granted' as const))
    vi.stubGlobal('Notification', { permission: 'default', requestPermission })

    draw()
    expect(requestPermission).not.toHaveBeenCalled()

    await user.click(screen.getByTestId('inbox-notify'))

    await waitFor(() => {
      expect(usePrefs.getState().notifications).toBe(true)
    })
    expect(requestPermission).toHaveBeenCalledTimes(1)
    expect(screen.getByTestId('inbox-notify')).toHaveAttribute('aria-pressed', 'true')
  })

  it('leaves the setting off, and says so, when the browser refuses', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('Notification', {
      permission: 'denied',
      requestPermission: vi.fn(() => Promise.resolve('denied' as const)),
    })

    draw()
    await user.click(screen.getByTestId('inbox-notify'))

    await waitFor(() => {
      expect(toast).toHaveBeenCalledWith(
        'this browser will not show notifications for Athanore',
      )
    })
    expect(usePrefs.getState().notifications).toBe(false)
  })

  it('turns itself off again without asking anybody', async () => {
    const user = userEvent.setup()
    const requestPermission = vi.fn(() => Promise.resolve('granted' as const))
    vi.stubGlobal('Notification', { permission: 'granted', requestPermission })
    usePrefs.setState({ notifications: true })

    draw()
    await user.click(screen.getByTestId('inbox-notify'))

    expect(usePrefs.getState().notifications).toBe(false)
    expect(requestPermission).not.toHaveBeenCalled()
  })

  it('draws no toggle at all in a browser with nothing to opt in to', () => {
    // `vi.stubGlobal(…, undefined)` leaves the key present, which is what
    // `'Notification' in window` tests, so the property is removed.
    const held = Reflect.get(globalThis, 'Notification') as unknown
    Reflect.deleteProperty(globalThis, 'Notification')
    try {
      draw()
      expect(screen.queryByTestId('inbox-notify')).not.toBeInTheDocument()
    } finally {
      if (held !== undefined) Reflect.set(globalThis, 'Notification', held)
    }
  })
})

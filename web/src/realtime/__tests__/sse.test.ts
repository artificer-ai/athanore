import { QueryClient } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createAppQueryClient, meQueryOptions } from '../../api/client'
import { manifestApiPluginsGetQueryKey } from '../../api/gen/@tanstack/react-query.gen'
import type { Me } from '../../api/gen/types.gen'
import { usePrefs } from '../../store/prefs'
import { useUi } from '../../store/ui'
import { clearRefreshOn, queryKeys, registerRefreshOn } from '../invalidate'
import {
  DOWN_AFTER_FAILURES,
  EVENT_NAMES,
  EventFeed,
  RECONNECT_MAX_MS,
  RECONNECT_MIN_MS,
  RESYNC,
  type EventSourceLike,
} from '../sse'

const LOOPBACK: Me = {
  auth: 'off',
  authenticated: true,
  features: [],
  started_at: '2026-09-08T09:00:00Z',
  version: '0.1.0',
}

/**
 * A stream a test drives by hand: it records what was subscribed to and
 * dispatches frames on command, which is all the browser does for us.
 */
class FakeEventSource implements EventSourceLike {
  readonly listeners = new Map<string, ((event: Event) => void)[]>()
  readonly url: string
  closed = false

  constructor(url: string) {
    this.url = url
  }

  addEventListener(type: string, listener: (event: Event) => void): void {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener])
  }

  close(): void {
    this.closed = true
  }

  /** Every listener for `type`, in the order they were added. */
  emit(type: string, event: Event): void {
    for (const listener of this.listeners.get(type) ?? []) listener(event)
  }

  open(): void {
    this.emit('open', new Event('open'))
  }

  fail(): void {
    this.emit('error', new Event('error'))
  }

  /** One frame: `event: name`, `data: <json>`, and an `id:` if stored. */
  frame(name: string, data: unknown, id?: string): void {
    this.emit(
      name,
      new MessageEvent(name, {
        data: JSON.stringify(data),
        ...(id === undefined ? {} : { lastEventId: id }),
      }),
    )
  }
}

/**
 * A feed over fake streams, with the streams it opened.
 *
 * Only `open` is injected: the state goes to the `useUi` store, which is
 * where the header and the banner read it from, so the assertions here
 * are about the thing on screen rather than about a callback.
 */
function feedOn(queryClient: QueryClient) {
  const opened: FakeEventSource[] = []
  const feed = new EventFeed(queryClient, {
    open: (url) => {
      const source = new FakeEventSource(url)
      opened.push(source)
      return source
    },
  })
  const latest = () => {
    const source = opened.at(-1)
    if (!source) throw new Error('the feed opened no stream')
    return source
  }
  return { feed, opened, latest }
}

describe('EventFeed', () => {
  let queryClient: QueryClient

  beforeEach(() => {
    vi.useFakeTimers()
    clearRefreshOn()
    usePrefs.setState({ token: null })
    useUi.setState({ feed: { status: 'reconnecting', retryAt: null } })
    queryClient = createAppQueryClient()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  describe('the connection', () => {
    it('opens one stream, at /api/events, with no cursor to replay from', () => {
      const { feed, opened } = feedOn(queryClient)

      feed.start()

      expect(opened).toHaveLength(1)
      expect(opened[0]?.url).toBe('/api/events')
    })

    it('opens nothing a second time, so a StrictMode remount is one stream', () => {
      const { feed, opened } = feedOn(queryClient)

      feed.start()
      feed.start()

      expect(opened).toHaveLength(1)
    })

    it('subscribes to every event name the contract defines', () => {
      const { feed, latest } = feedOn(queryClient)

      feed.start()

      // A browser delivers a named frame only to a listener for that
      // name, so a name nobody subscribed to is a name nobody hears.
      for (const name of EVENT_NAMES) {
        expect(latest().listeners.has(name)).toBe(true)
      }
      expect(latest().listeners.has(RESYNC)).toBe(true)
    })

    it('subscribes to a plugin’s own event name when a panel registers it', () => {
      const { feed, latest } = feedOn(queryClient)
      feed.start()

      registerRefreshOn(['plugin.demo.counted'], [['panel', 'counter']])

      expect(latest().listeners.has('plugin.demo.counted')).toBe(true)
    })

    it('closes the stream and stops retrying when it is stopped', () => {
      const { feed, latest, opened } = feedOn(queryClient)
      feed.start()
      latest().fail()

      feed.stop()
      vi.advanceTimersByTime(RECONNECT_MAX_MS * 4)

      expect(opened).toHaveLength(1)
      expect(opened[0]?.closed).toBe(true)
    })
  })

  describe('the credential', () => {
    it('appends the token on a server that wants one', () => {
      queryClient.setQueryData(meQueryOptions().queryKey, {
        ...LOOPBACK,
        auth: 'token',
      })
      usePrefs.setState({ token: 's3cret' })
      const { feed, opened } = feedOn(queryClient)

      feed.start()

      // The one place a token legitimately rides in a query string:
      // `EventSource` cannot set a header (08 §Auth).
      expect(opened[0]?.url).toBe('/api/events?access_token=s3cret')
    })

    it('withholds it from a server that has said auth is off', () => {
      queryClient.setQueryData(meQueryOptions().queryKey, LOOPBACK)
      usePrefs.setState({ token: 'left-over-from-somewhere-else' })
      const { feed, opened } = feedOn(queryClient)

      feed.start()

      expect(opened[0]?.url).toBe('/api/events')
    })

    it('reconnects at once when the operator supplies a token', () => {
      const { feed, opened, latest } = feedOn(queryClient)
      feed.start()
      latest().fail()

      usePrefs.setState({ token: 's3cret' })

      // Otherwise a login that plainly worked would leave the app deaf
      // for the rest of a 30 s backoff.
      expect(opened).toHaveLength(2)
      expect(opened[1]?.url).toBe('/api/events?access_token=s3cret')
    })
  })

  describe('the cursor', () => {
    it('reconnects with after=<the last id it saw>', () => {
      const { feed, opened, latest } = feedOn(queryClient)
      feed.start()

      latest().open()
      latest().frame('run.started', { name: 'run.started', run_id: 'r1', data: {} }, '41')
      latest().fail()
      vi.advanceTimersByTime(RECONNECT_MIN_MS)

      expect(feed.lastId).toBe('41')
      expect(opened[1]?.url).toBe('/api/events?after=41')
    })

    it('keeps the cursor an ephemeral frame does not move', () => {
      const { feed, latest } = feedOn(queryClient)
      feed.start()
      latest().open()

      latest().frame('task.done', { name: 'task.done', run_id: 'r1', data: {} }, '41')
      // `task.stream` is sent without an `id:` (08 §Events), so the
      // cursor always names a row the server can replay from.
      latest().frame('task.stream', {
        name: 'task.stream',
        run_id: 'r1',
        task_id: 7,
        data: { seq_from: 1, seq_to: 2 },
      })

      expect(feed.lastId).toBe('41')
    })
  })

  describe('resync', () => {
    it('clears the cache and the cursor', () => {
      const invalidate = vi
        .spyOn(queryClient, 'invalidateQueries')
        .mockResolvedValue(undefined)
      const { feed, opened, latest } = feedOn(queryClient)
      feed.start()
      latest().open()
      latest().frame('run.started', { name: 'run.started', run_id: 'r1', data: {} }, '41')

      latest().frame(RESYNC, { reason: 'replay_capped' })

      // Everything this tab holds may be missing something, and the
      // cursor names an event the server will no longer serve from.
      expect(invalidate).toHaveBeenCalledWith()
      expect(feed.lastId).toBeNull()

      latest().fail()
      vi.advanceTimersByTime(RECONNECT_MIN_MS)
      expect(opened[1]?.url).toBe('/api/events')
    })
  })

  describe('the backoff', () => {
    it('doubles from a second and stops at thirty', () => {
      const { feed, opened, latest } = feedOn(queryClient)
      feed.start()

      const delays = [1000, 2000, 4000, 8000, 16000, 30000, 30000]
      for (const [index, delay] of delays.entries()) {
        latest().fail()
        vi.advanceTimersByTime(delay - 1)
        expect(opened).toHaveLength(index + 1)
        vi.advanceTimersByTime(1)
        expect(opened).toHaveLength(index + 2)
      }
      expect(RECONNECT_MIN_MS).toBe(1000)
      expect(RECONNECT_MAX_MS).toBe(30000)
    })

    it('starts over once the stream is back', () => {
      const { feed, opened, latest } = feedOn(queryClient)
      feed.start()
      latest().fail()
      vi.advanceTimersByTime(RECONNECT_MIN_MS)
      latest().open()

      latest().fail()
      vi.advanceTimersByTime(RECONNECT_MIN_MS)

      expect(opened).toHaveLength(3)
    })

    it('tries now when asked, without waiting the backoff out', () => {
      const { feed, opened, latest } = feedOn(queryClient)
      feed.start()
      latest().fail()

      feed.reconnectNow()

      expect(opened).toHaveLength(2)
      vi.advanceTimersByTime(RECONNECT_MAX_MS)
      // The timer that was pending was dropped rather than left to fire.
      expect(opened).toHaveLength(2)
    })
  })

  describe('the status', () => {
    it('is open while the stream is', () => {
      const { feed, latest } = feedOn(queryClient)
      feed.start()

      latest().open()

      expect(feed.status).toBe('open')
      expect(useUi.getState().feed).toEqual({ status: 'open', retryAt: null })
    })

    it('says nothing on screen about a single dropped connection', () => {
      const { feed, latest } = feedOn(queryClient)
      feed.start()
      latest().open()

      latest().fail()

      expect(feed.status).toBe('reconnecting')
      expect(DOWN_AFTER_FAILURES).toBe(2)
    })

    it('goes down once a retry has failed too, with the next attempt due', () => {
      vi.setSystemTime(new Date('2026-09-08T09:00:00Z'))
      const { feed, latest } = feedOn(queryClient)
      feed.start()
      latest().open()

      latest().fail()
      vi.advanceTimersByTime(RECONNECT_MIN_MS)
      latest().fail()

      expect(feed.status).toBe('down')
      expect(useUi.getState().feed.retryAt).toBe(Date.now() + 2000)
    })
  })

  describe('coming back', () => {
    it('refetches /api/me, and leaves the manifest alone when nothing restarted', async () => {
      queryClient.setQueryData(meQueryOptions().queryKey, LOOPBACK)
      const refetch = vi.spyOn(queryClient, 'refetchQueries').mockResolvedValue(undefined)
      const { feed, latest } = feedOn(queryClient)
      feed.start()
      latest().open()

      latest().fail()
      vi.advanceTimersByTime(RECONNECT_MIN_MS)
      latest().open()
      await vi.waitFor(() => expect(refetch).toHaveBeenCalled())

      expect(refetch).toHaveBeenCalledExactlyOnceWith({
        queryKey: meQueryOptions().queryKey,
      })
    })

    it('refetches the plugin manifest when the server restarted under it', async () => {
      queryClient.setQueryData(meQueryOptions().queryKey, LOOPBACK)
      const refetch = vi
        .spyOn(queryClient, 'refetchQueries')
        .mockImplementation(async () => {
          // What a restarted server answers: a new `started_at` (09).
          queryClient.setQueryData(meQueryOptions().queryKey, {
            ...LOOPBACK,
            started_at: '2026-09-08T11:30:00Z',
          })
        })
      const { feed, latest } = feedOn(queryClient)
      feed.start()
      latest().open()

      latest().fail()
      vi.advanceTimersByTime(RECONNECT_MIN_MS)
      latest().open()
      await vi.waitFor(() => expect(refetch).toHaveBeenCalledTimes(2))

      expect(refetch).toHaveBeenLastCalledWith({
        queryKey: manifestApiPluginsGetQueryKey(),
      })
    })

    it('asks nothing extra of the first connection of a page', async () => {
      queryClient.setQueryData(meQueryOptions().queryKey, LOOPBACK)
      const refetch = vi.spyOn(queryClient, 'refetchQueries').mockResolvedValue(undefined)
      const { feed, latest } = feedOn(queryClient)

      feed.start()
      latest().open()
      await Promise.resolve()

      // The page has just fetched both by itself.
      expect(refetch).not.toHaveBeenCalled()
    })
  })

  describe('the frames', () => {
    it('sends what it hears through the invalidation table', () => {
      const invalidate = vi
        .spyOn(queryClient, 'invalidateQueries')
        .mockResolvedValue(undefined)
      const { feed, latest } = feedOn(queryClient)
      feed.start()
      latest().open()

      latest().frame(
        'log.appended',
        { name: 'log.appended', run_id: 'r1', task_id: 7, data: {} },
        '9',
      )
      vi.advanceTimersByTime(250)

      expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.log('r1') })
    })

    it('drops a frame that is not an event rather than throwing on it', () => {
      const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
      const invalidate = vi
        .spyOn(queryClient, 'invalidateQueries')
        .mockResolvedValue(undefined)
      const { feed, latest } = feedOn(queryClient)
      feed.start()
      latest().open()

      latest().emit(
        'run.started',
        new MessageEvent('run.started', { data: 'not json', lastEventId: '9' }),
      )
      latest().frame('run.started', { run_id: 'r1' }, '10')
      vi.advanceTimersByTime(250)

      expect(invalidate).not.toHaveBeenCalled()
      expect(warn).toHaveBeenCalledTimes(2)
      // The cursor still moved: the server sent those ids, whatever the
      // bodies were, and replaying them again would not improve them.
      expect(feed.lastId).toBe('10')
    })
  })
})

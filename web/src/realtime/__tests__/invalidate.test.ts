import type { QueryClient } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest'

import { createAppQueryClient } from '../../api/client'
import type { StreamOut } from '../../api/gen/types.gen'
import {
  COALESCE_WINDOW_MS,
  Invalidator,
  clearRefreshOn,
  keysFor,
  queryKeys,
  registerRefreshOn,
  type AthanoreEvent,
} from '../invalidate'

/** An envelope off the feed, with only the fields the table reads. */
function event(
  name: string,
  fields: { run_id?: string; task_id?: number; data?: unknown } = {},
): AthanoreEvent {
  return {
    name,
    created: '2026-09-08T09:00:00Z',
    data: fields.data ?? {},
    ...(fields.run_id === undefined ? {} : { run_id: fields.run_id }),
    ...(fields.task_id === undefined ? {} : { task_id: fields.task_id }),
  } as AthanoreEvent
}

/** The keys as strings, which is how the matcher compares them too. */
function names(keys: readonly unknown[]): string[] {
  return keys.map((key) => JSON.stringify(key))
}

describe('the invalidation table', () => {
  beforeEach(() => {
    clearRefreshOn()
  })

  describe('the matcher', () => {
    it('lets an exact name win outright, so task.stream never hits task.*', () => {
      const keys = keysFor(event('task.stream', { run_id: 'r1', task_id: 7 }))

      // The whole point of first-exact-then-glob: two or three of these
      // arrive per second per streaming task (10 §Realtime).
      expect(names(keys)).toEqual(names([queryKeys.stream(7)]))
      expect(names(keys)).not.toContain(JSON.stringify(queryKeys.task(7)))
      expect(names(keys)).not.toContain(JSON.stringify(queryKeys.run('r1')))
      expect(names(keys)).not.toContain(JSON.stringify(queryKeys.graph('r1')))
      expect(names(keys)).not.toContain(JSON.stringify(queryKeys.runs()))
    })

    it('falls through to the glob for every other task event', () => {
      const keys = names(keysFor(event('task.done', { run_id: 'r1', task_id: 7 })))

      expect(keys).toContain(JSON.stringify(queryKeys.run('r1')))
      expect(keys).toContain(JSON.stringify(queryKeys.graph('r1')))
      expect(keys).toContain(JSON.stringify(queryKeys.task(7)))
      // The list's STATUS and NODE cells move with the tasks (10).
      expect(keys).toContain(JSON.stringify(queryKeys.runs()))
      expect(keys).not.toContain(JSON.stringify(queryKeys.stream(7)))
    })

    it('refetches the list, the run and the graph on a run event', () => {
      const keys = names(keysFor(event('run.started', { run_id: 'r1' })))

      expect(keys).toEqual(
        names([queryKeys.runs(), queryKeys.run('r1'), queryKeys.graph('r1')]),
      )
    })

    it('takes log.appended exactly, and only the run’s log with it', () => {
      const keys = names(keysFor(event('log.appended', { run_id: 'r1', task_id: 7 })))

      expect(keys).toEqual(names([queryKeys.log('r1')]))
    })

    it('refetches the run’s requests and the inbox on a request event', () => {
      const keys = names(keysFor(event('request.opened', { run_id: 'r1' })))

      expect(keys).toEqual(names([queryKeys.requests('r1'), queryKeys.inbox()]))
    })

    it('refetches only the run on agent.stats', () => {
      const keys = names(keysFor(event('agent.stats', { run_id: 'r1', task_id: 7 })))

      expect(keys).toEqual(names([queryKeys.run('r1')]))
    })

    it('answers with nothing for a name no row matches', () => {
      expect(keysFor(event('submission.accepted', { run_id: 'r1' }))).toEqual([])
    })

    it('drops the keys an event carries no id for', () => {
      // `engine.*` events carry no `run_id` (18 §Rules), and a key built
      // from `undefined` would match every run in the cache.
      expect(keysFor(event('log.appended'))).toEqual([])
    })
  })

  describe('plugin panels', () => {
    it('refreshes a panel on the core event it registered for', () => {
      registerRefreshOn(['log.appended'], [['panel', 'words']])

      const keys = names(keysFor(event('log.appended', { run_id: 'r1' })))

      expect(keys).toEqual(names([queryKeys.log('r1'), ['panel', 'words']]))
    })

    it('refreshes a panel on a plugin’s own event name', () => {
      registerRefreshOn(['plugin.demo.counted'], [['panel', 'counter']])

      expect(names(keysFor(event('plugin.demo.counted', { run_id: 'r1' })))).toEqual(
        names([['panel', 'counter']]),
      )
    })

    it('leaves a plugin event nobody registered for alone', () => {
      expect(keysFor(event('plugin.demo.counted', { run_id: 'r1' }))).toEqual([])
    })

    it('forgets everything when the manifest is reloaded', () => {
      registerRefreshOn(['plugin.demo.counted'], [['panel', 'counter']])
      clearRefreshOn()

      expect(keysFor(event('plugin.demo.counted'))).toEqual([])
    })
  })
})

describe('the coalescer', () => {
  let queryClient: QueryClient
  let invalidate: MockInstance<QueryClient['invalidateQueries']>

  beforeEach(() => {
    vi.useFakeTimers()
    clearRefreshOn()
    queryClient = createAppQueryClient()
    invalidate = vi.spyOn(queryClient, 'invalidateQueries').mockResolvedValue(undefined)
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  /** The keys invalidated so far, serialised. */
  function invalidated(): string[] {
    return invalidate.mock.calls.map(([filters]) => JSON.stringify(filters?.queryKey))
  }

  it('merges duplicate keys inside the window into one refetch', () => {
    const invalidator = new Invalidator(queryClient)

    // Three events, all of them about the same run.
    invalidator.handle(event('run.started', { run_id: 'r1' }))
    invalidator.handle(event('run.updated', { run_id: 'r1' }))
    invalidator.handle(event('agent.stats', { run_id: 'r1', task_id: 7 }))

    expect(invalidate).not.toHaveBeenCalled()

    vi.advanceTimersByTime(COALESCE_WINDOW_MS)

    expect(invalidated()).toEqual(
      [queryKeys.runs(), queryKeys.run('r1'), queryKeys.graph('r1')].map((key) =>
        JSON.stringify(key),
      ),
    )
  })

  it('waits the whole window before invalidating anything', () => {
    const invalidator = new Invalidator(queryClient)

    invalidator.handle(event('run.started', { run_id: 'r1' }))
    vi.advanceTimersByTime(COALESCE_WINDOW_MS - 1)
    expect(invalidate).not.toHaveBeenCalled()

    vi.advanceTimersByTime(1)
    expect(invalidate).toHaveBeenCalledTimes(3)
  })

  it('opens a new window for what arrives after a flush', () => {
    const invalidator = new Invalidator(queryClient)

    invalidator.handle(event('run.started', { run_id: 'r1' }))
    vi.advanceTimersByTime(COALESCE_WINDOW_MS)
    invalidator.handle(event('run.started', { run_id: 'r1' }))
    vi.advanceTimersByTime(COALESCE_WINDOW_MS)

    expect(invalidate).toHaveBeenCalledTimes(6)
  })

  it('drops what is pending when it is disposed', () => {
    const invalidator = new Invalidator(queryClient)

    invalidator.handle(event('run.started', { run_id: 'r1' }))
    invalidator.dispose()
    vi.advanceTimersByTime(COALESCE_WINDOW_MS * 4)

    expect(invalidate).not.toHaveBeenCalled()
  })
})

describe('the transcript', () => {
  let queryClient: QueryClient

  const page = (chunks: number[], lastSeq: number, live = true): StreamOut => ({
    chunks: chunks.map((seq) => ({
      seq,
      kind: 'text',
      text: `chunk ${seq}`,
      created: '2026-09-08T09:00:00Z',
    })),
    last_seq: lastSeq,
    live,
  })

  /** Answer the stream endpoint with `body`, and record the URLs asked for. */
  function stubStream(body: StreamOut) {
    const fetchMock = vi.fn(
      async (_request: Request) =>
        new Response(JSON.stringify(body), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
    )
    vi.stubGlobal('fetch', fetchMock)
    return fetchMock
  }

  beforeEach(() => {
    clearRefreshOn()
    queryClient = createAppQueryClient()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('appends the chunks the event announced instead of refetching', async () => {
    queryClient.setQueryData(queryKeys.stream(7), page([1, 2], 2))
    const fetchMock = stubStream(page([3, 4], 4))
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')

    await new Invalidator(queryClient).appendStream(7, 3)

    const held = queryClient.getQueryData<StreamOut>(queryKeys.stream(7))
    expect(held?.chunks.map((chunk) => chunk.seq)).toEqual([1, 2, 3, 4])
    expect(held?.last_seq).toBe(4)
    // The whole of the point: one small page, and no invalidation that
    // would have thrown the transcript away and fetched it again.
    expect(fetchMock).toHaveBeenCalledOnce()
    expect(invalidate).not.toHaveBeenCalled()
  })

  it('asks for everything after what the cache holds', async () => {
    queryClient.setQueryData(queryKeys.stream(7), page([1, 2], 2))
    const fetchMock = stubStream(page([3], 3))

    await new Invalidator(queryClient).appendStream(7, 3)

    expect(fetchMock.mock.calls[0]?.[0].url).toContain('after=2')
  })

  it('reaches back past the cursor when a frame was missed', async () => {
    // The event says 9 is new; this tab only ever saw 2, so the four
    // chunks in between would otherwise be a permanent hole.
    queryClient.setQueryData(queryKeys.stream(7), page([1, 2], 2))
    const fetchMock = stubStream(page([3, 4, 5, 6, 7, 8, 9], 9))

    await new Invalidator(queryClient).appendStream(7, 9)

    expect(fetchMock.mock.calls[0]?.[0].url).toContain('after=2')
  })

  it('fetches nothing for a transcript nobody is holding', async () => {
    const fetchMock = stubStream(page([1], 1))

    await new Invalidator(queryClient).appendStream(7, 1)

    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('never duplicates a chunk it already holds', async () => {
    queryClient.setQueryData(queryKeys.stream(7), page([1, 2, 3], 3))
    stubStream(page([2, 3, 4], 4))

    await new Invalidator(queryClient).appendStream(7, 4)

    expect(
      queryClient.getQueryData<StreamOut>(queryKeys.stream(7))?.chunks.map((c) => c.seq),
    ).toEqual([1, 2, 3, 4])
  })

  it('marks the transcript stale when the page could not be fetched', async () => {
    queryClient.setQueryData(queryKeys.stream(7), page([1], 1))
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new Error('the server went away')
      }),
    )
    const invalidator = new Invalidator(queryClient)
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries').mockResolvedValue()

    await invalidator.appendStream(7, 2)
    invalidator.flush()

    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.stream(7) })
  })

  it('routes a task.stream event to the append rather than the table', async () => {
    queryClient.setQueryData(queryKeys.stream(7), page([1], 1))
    const fetchMock = stubStream(page([2], 2))
    const invalidator = new Invalidator(queryClient)

    invalidator.handle(
      event('task.stream', {
        run_id: 'r1',
        task_id: 7,
        data: { seq_from: 2, seq_to: 2 },
      }),
    )
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledOnce())

    expect(
      queryClient.getQueryData<StreamOut>(queryKeys.stream(7))?.chunks.map((c) => c.seq),
    ).toEqual([1, 2])
  })
})

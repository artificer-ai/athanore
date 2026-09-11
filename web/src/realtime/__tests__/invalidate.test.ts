import type { QueryClient } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest'

import { createAppQueryClient } from '../../api/client'
import {
  getSourceApiWorkflowsNameSourceGetQueryKey,
  getWorkflowApiWorkflowsNameGetQueryKey,
} from '../../api/gen/@tanstack/react-query.gen'
import type { StreamOut } from '../../api/gen/types.gen'
import {
  COALESCE_WINDOW_MS,
  Invalidator,
  clearRefreshOn,
  keysFor,
  panelsRefreshingOn,
  queryKeys,
  registerRefreshOn,
  subscribeRefreshOn,
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

    it('refetches the run list too on a request event, for the row’s ⚠', () => {
      // A permission opens mid-turn, while its task is still
      // `in_progress`, so no `task.*` follows it to refresh the list.
      // `GET /api/runs` carries `pending_requests` (D208).
      const keys = names(keysFor(event('request.opened', { run_id: 'r1' })))

      expect(keys).toEqual(
        names([
          queryKeys.runs(),
          queryKeys.run('r1'),
          queryKeys.requests('r1'),
          queryKeys.inbox(),
        ]),
      )
    })

    it('still refetches the list when a request event carries no run', () => {
      const keys = names(keysFor(event('request.answered', {})))

      expect(keys).toEqual(names([queryKeys.runs(), queryKeys.inbox()]))
    })

    it('refetches only the run on agent.stats', () => {
      const keys = names(keysFor(event('agent.stats', { run_id: 'r1', task_id: 7 })))

      expect(keys).toEqual(names([queryKeys.run('r1')]))
    })

    describe('workflow.*', () => {
      /** 22 §SPA's four, and the run list (D253). */
      const registrationKeys = () =>
        names([
          queryKeys.workflows(),
          queryKeys.workflow(),
          queryKeys.source(),
          queryKeys.manifest(),
          queryKeys.runs(),
        ])

      it.each(['workflow.registered', 'workflow.replaced', 'workflow.unregistered'])(
        'refetches the library, the manifest and the run list on %s',
        (name) => {
          // The three carry no `run_id` (22 §Wire), and the row asks for
          // none: a registration is about every workflow's list.
          const keys = names(keysFor(event(name)))

          expect(keys).toEqual(registrationKeys())
          expect(keys).not.toContain(JSON.stringify(queryKeys.run('r1')))
          expect(keys).not.toContain(JSON.stringify(queryKeys.task(7)))
          expect(keys).not.toContain(JSON.stringify(queryKeys.stream(7)))
        },
      )

      it('names the single-workflow and source queries of every name at once', async () => {
        // The generated keys carry `path: { name }`; the row's prefix is
        // the same object with `path` taken off, which TanStack's deep
        // partial matching reaches for any name (D155, D253).
        const queryClient = createAppQueryClient()
        const tempo = getWorkflowApiWorkflowsNameGetQueryKey({ path: { name: 'tempo' } })
        const tempoSource = getSourceApiWorkflowsNameSourceGetQueryKey({
          path: { name: 'tempo' },
        })
        const probeSource = getSourceApiWorkflowsNameSourceGetQueryKey({
          path: { name: 'probe' },
        })
        queryClient.setQueryData(tempo, { name: 'tempo' })
        queryClient.setQueryData(tempoSource, { source: 'v1' })
        queryClient.setQueryData(probeSource, { source: 'v1' })

        const [prefix] = queryKeys.workflow() as [Record<string, unknown>]
        expect(prefix).not.toHaveProperty('path')
        expect(prefix._id).toBe((tempo[0] as Record<string, unknown>)._id)
        expect(prefix.baseUrl).toBe((tempo[0] as Record<string, unknown>).baseUrl)
        expect(
          queryClient.getQueryCache().findAll({ queryKey: queryKeys.workflow() }),
        ).toHaveLength(1)
        expect(
          queryClient
            .getQueryCache()
            .findAll({ queryKey: queryKeys.source() })
            .map((query) => query.queryKey),
        ).toEqual([tempoSource, probeSource])

        await queryClient.invalidateQueries({ queryKey: queryKeys.source() })

        expect(queryClient.getQueryState(tempoSource)?.isInvalidated).toBe(true)
        expect(queryClient.getQueryState(probeSource)?.isInvalidated).toBe(true)
        expect(queryClient.getQueryState(tempo)?.isInvalidated).toBe(false)
      })
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

    it('matches a panel’s `refresh_on` glob against the name that arrived', () => {
      // `refresh_on` is a list of globs (09 §Wire contract), matched the
      // same first-exact-then-glob way the table's own rows are — but
      // over the registrations, where an exact one is not exclusive.
      registerRefreshOn(['task.*'], [['panel', 'progress']])

      expect(names(keysFor(event('task.done', { run_id: 'r1', task_id: 7 })))).toContain(
        JSON.stringify(['panel', 'progress']),
      )
    })

    it('refreshes two panels that spelled the same event differently', () => {
      registerRefreshOn(['task.done'], [['panel', 'exact']])
      registerRefreshOn(['task.*'], [['panel', 'globbed']])

      expect(names(panelsRefreshingOn('task.done'))).toEqual(
        names([
          ['panel', 'exact'],
          ['panel', 'globbed'],
        ]),
      )
    })

    it('joins a name that is already registered rather than replacing it', () => {
      // "a name that is already a row joins it" (10 §Realtime and
      // caching): two panels of one manifest can watch one event.
      registerRefreshOn(['log.appended'], [['panel', 'words']])
      registerRefreshOn(['log.appended'], [['panel', 'budget']])
      registerRefreshOn(['log.appended'], [['panel', 'words']])

      expect(names(panelsRefreshingOn('log.appended'))).toEqual(
        names([
          ['panel', 'words'],
          ['panel', 'budget'],
        ]),
      )
    })

    it('tells the feed which names are registered, now and on every change', () => {
      const heard: string[][] = []
      const unsubscribe = subscribeRefreshOn((registered) => {
        heard.push([...registered])
      })

      // A browser's `EventSource` delivers a named frame only to a
      // listener for that name, so the feed has to be told (`sse.ts`).
      expect(heard).toEqual([[]])

      registerRefreshOn(['plugin.demo.counted'], [['panel', 'counter']])
      expect(heard.at(-1)).toEqual(['plugin.demo.counted'])

      unsubscribe()
      registerRefreshOn(['plugin.demo.tocked'], [['panel', 'clock']])
      expect(heard).toHaveLength(2)
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

  it('coalesces the three registration names into one refetch each', () => {
    const invalidator = new Invalidator(queryClient)

    // A reload is `workflow.replaced`; a `rm` then an `add` of one name
    // inside a window is two more. Five keys, once each.
    invalidator.handle(event('workflow.replaced'))
    invalidator.handle(event('workflow.unregistered'))
    invalidator.handle(event('workflow.registered'))

    vi.advanceTimersByTime(COALESCE_WINDOW_MS)

    expect(invalidated()).toEqual(
      [
        queryKeys.workflows(),
        queryKeys.workflow(),
        queryKeys.source(),
        queryKeys.manifest(),
        queryKeys.runs(),
      ].map((key) => JSON.stringify(key)),
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

  it('flushes early when it is asked to, and lets the window lapse', () => {
    const invalidator = new Invalidator(queryClient)

    invalidator.handle(event('log.appended', { run_id: 'r1' }))
    invalidator.flush()
    expect(invalidated()).toEqual([JSON.stringify(queryKeys.log('r1'))])

    // The timer the window opened was cleared, not left to fire on an
    // empty set a second time.
    vi.advanceTimersByTime(COALESCE_WINDOW_MS * 4)
    expect(invalidate).toHaveBeenCalledTimes(1)
  })

  it('coalesces a burst of stream events into one refetch per panel', () => {
    // A panel that asked for `task.stream` outright is refreshed at the
    // stream's own rate — that is what asking for it means — but the
    // window still collapses a tick of them into one.
    registerRefreshOn(['task.stream'], [['panel', 'progress']])
    const invalidator = new Invalidator(queryClient)

    for (let seq = 1; seq <= 5; seq += 1) {
      invalidator.handle(
        event('task.stream', { task_id: 7, data: { seq_from: seq, seq_to: seq } }),
      )
    }
    vi.advanceTimersByTime(COALESCE_WINDOW_MS)

    expect(invalidated()).toEqual([JSON.stringify(['panel', 'progress'])])
  })

  it('leaves a panel that only globbed `task.*` out of the stream’s rate', () => {
    // Two or three of these arrive per second per streaming task; a
    // panel refreshing on `task.*` did not ask for that (10 §Realtime).
    registerRefreshOn(['task.*'], [['panel', 'progress']])
    const invalidator = new Invalidator(queryClient)

    invalidator.handle(
      event('task.stream', { task_id: 7, data: { seq_from: 1, seq_to: 1 } }),
    )
    vi.advanceTimersByTime(COALESCE_WINDOW_MS)

    expect(invalidate).not.toHaveBeenCalled()
  })

  it.each([
    ['no task id', { data: { seq_from: 1, seq_to: 1 } }],
    ['a payload that is not a stream page', { task_id: 7, data: { chunks: [] } }],
  ])('appends nothing for a task.stream carrying %s', (_case, fields) => {
    const append = vi.spyOn(Invalidator.prototype, 'appendStream')
    const invalidator = new Invalidator(queryClient)

    invalidator.handle(event('task.stream', fields))
    vi.advanceTimersByTime(COALESCE_WINDOW_MS)

    expect(append).not.toHaveBeenCalled()
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

  it('leaves the cached page alone when the fetch brought nothing new', async () => {
    const held = page([1, 2], 2)
    queryClient.setQueryData(queryKeys.stream(7), held)
    stubStream(page([1, 2], 2))

    await new Invalidator(queryClient).appendStream(7, 3)

    // The same object, so nothing downstream re-renders on a page the
    // viewer already had.
    expect(queryClient.getQueryData<StreamOut>(queryKeys.stream(7))).toBe(held)
  })

  it('marks the transcript stale when the server refused the page', async () => {
    queryClient.setQueryData(queryKeys.stream(7), page([1], 1))
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response(JSON.stringify({ error: 'no such task', code: 'not_found' }), {
            status: 404,
            headers: { 'Content-Type': 'application/json' },
          }),
      ),
    )
    const invalidator = new Invalidator(queryClient)
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries').mockResolvedValue()

    await invalidator.appendStream(7, 2)
    invalidator.flush()

    // Stale rather than wrong: the view refetches it whole.
    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.stream(7) })
  })

  it('marks the transcript stale when the fetch itself threw', async () => {
    queryClient.setQueryData(queryKeys.stream(7), page([1], 1))
    vi.stubGlobal(
      'fetch',
      vi.fn(() => {
        throw new TypeError('Failed to fetch')
      }),
    )
    const invalidator = new Invalidator(queryClient)
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries').mockResolvedValue()

    await invalidator.appendStream(7, 2)
    invalidator.flush()

    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.stream(7) })
  })

  it('marks a page it cannot merge stale rather than fetching one', async () => {
    // An infinite query, say: the shape is not a `StreamOut` and merging
    // into it would corrupt it. Slower and still correct.
    queryClient.setQueryData(queryKeys.stream(7), { pages: [], pageParams: [] })
    const fetchMock = stubStream(page([2], 2))
    const invalidator = new Invalidator(queryClient)
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries').mockResolvedValue()

    await invalidator.appendStream(7, 2)
    invalidator.flush()

    expect(fetchMock).not.toHaveBeenCalled()
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

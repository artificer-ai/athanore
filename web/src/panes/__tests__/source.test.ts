import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createAppQueryClient } from '../../api/client'
import type { PanelOut } from '../../api/gen/types.gen'
import {
  clearRefreshOn,
  keysFor,
  queryKeys,
  Invalidator,
  type AthanoreEvent,
} from '../../realtime/invalidate'
import {
  PanelSourceError,
  fetchPanel,
  panelParams,
  panelQueryKey,
  registerPanelRefresh,
} from '../source'
import { BUILTIN_ENTRY, GAMEDEV_ENTRY, MANIFEST, panel } from './fixtures'

/** The builtin overview panel, which is the one every run shows. */
const OVERVIEW = BUILTIN_ENTRY.panels?.[0] as PanelOut
const LOG = BUILTIN_ENTRY.panels?.[1] as PanelOut

/** An envelope off the feed, with only the fields the table reads. */
function event(name: string, fields: { run_id?: string; task_id?: number } = {}) {
  return {
    name,
    created: '2026-09-08T09:00:00Z',
    data: {},
    ...(fields.run_id === undefined ? {} : { run_id: fields.run_id }),
    ...(fields.task_id === undefined ? {} : { task_id: fields.task_id }),
  } as AthanoreEvent
}

const keyNames = (keys: readonly unknown[]) => keys.map((key) => JSON.stringify(key))

describe('panelParams', () => {
  it('asks a run-scoped panel with the selected run', () => {
    expect(panelParams(OVERVIEW, { runId: 'r1' })).toEqual({ run_id: 'r1' })
  })

  it('asks nothing of a run-scoped panel with no run in scope', () => {
    // 09 §Context and scopes makes a missing id a 404 before the handler
    // runs; a request that can only 404 is not worth making.
    expect(panelParams(OVERVIEW, {})).toBeNull()
  })

  it('asks a global panel with no ids at all', () => {
    const inbox = panel({ name: 'inbox', slot: 'global', scope: 'global' })

    expect(panelParams(inbox, {})).toEqual({})
  })

  it('asks a node panel with its own node, and only where there is a run', () => {
    const playfield = GAMEDEV_ENTRY.panels?.[3] as PanelOut

    expect(panelParams(playfield, { runId: 'r1' })).toEqual({
      run_id: 'r1',
      node: 'qa',
    })
    expect(panelParams(playfield, {})).toBeNull()
  })

  it('asks a task panel only once a task is focused', () => {
    const drawer = panel({ name: 'attempt', slot: 'task', scope: 'task' })

    expect(panelParams(drawer, { runId: 'r1' })).toBeNull()
    expect(panelParams(drawer, { runId: 'r1', taskId: 7 })).toEqual({
      run_id: 'r1',
      task_id: 7,
    })
  })
})

describe('panelQueryKey', () => {
  it('is a prefix of every scoped copy of one panel’s data', () => {
    const prefix = panelQueryKey('/api/plugins/_builtin/overview')
    const scoped = panelQueryKey('/api/plugins/_builtin/overview', { run_id: 'r1' })

    // TanStack matches a filter key partially, so one registration made
    // before a run was selected reaches every run's copy (D155).
    expect(scoped.slice(0, prefix.length)).toEqual(prefix)
  })
})

describe('registerPanelRefresh', () => {
  beforeEach(() => {
    clearRefreshOn()
  })

  it('registers a panel’s refresh_on names against its own query key', () => {
    registerPanelRefresh(MANIFEST)

    // `words` declares `refresh_on: ["log.appended"]` (09 §Declarations).
    expect(keyNames(keysFor(event('log.appended', { run_id: 'r1' })))).toEqual(
      keyNames([
        queryKeys.log('r1'),
        panelQueryKey('/api/plugins/_builtin/log'),
        panelQueryKey('/api/plugins/gamedev/words'),
      ]),
    )
  })

  it('matches a refresh_on glob, because that is what refresh_on is', () => {
    registerPanelRefresh(MANIFEST)

    // The overview registers `task.*` (`plugins/builtin/overview.py`).
    expect(keyNames(keysFor(event('task.done', { run_id: 'r1', task_id: 7 })))).toContain(
      JSON.stringify(panelQueryKey(OVERVIEW.source ?? '')),
    )
  })

  it('keeps a task.* panel out of the task.stream firehose', () => {
    registerPanelRefresh(MANIFEST)
    const queryClient = createAppQueryClient()
    const invalidator = new Invalidator(queryClient, 0)
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')

    invalidator.handle(event('task.stream', { run_id: 'r1', task_id: 7 }))
    invalidator.flush()

    // Two or three of these arrive per second per streaming task (10
    // §Realtime and caching); the overview is not refetched at that rate.
    expect(
      invalidate.mock.calls.map(([filters]) => JSON.stringify(filters?.queryKey)),
    ).not.toContain(JSON.stringify(panelQueryKey(OVERVIEW.source ?? '')))
  })

  it('registers nothing for a panel with no source to refetch', () => {
    registerPanelRefresh([
      {
        workflow: 'gamedev',
        panels: [
          // A `custom` panel: an element, and no URL behind it.
          panel({ name: 'playfield', refresh_on: ['run.*'] }),
          // A kind this build has no renderer for: its `source` answers
          // with a shape nothing here reads, so nothing refetches it.
          panel({
            name: 'timeline',
            kind: 'timeline' as PanelOut['kind'],
            source: '/api/plugins/gamedev/timeline',
            refresh_on: ['run.*'],
          }),
        ],
      },
    ])

    expect(keysFor(event('run.completed', { run_id: 'r1' }))).toEqual([
      queryKeys.runs(),
      queryKeys.run('r1'),
      queryKeys.graph('r1'),
    ])
  })

  it('forgets the panels of a manifest that was replaced', () => {
    registerPanelRefresh(MANIFEST)
    registerPanelRefresh([])

    expect(keysFor(event('log.appended', { run_id: 'r1' }))).toEqual([queryKeys.log('r1')])
  })

  it('leaves the log panel’s own key registered beside the log query', () => {
    registerPanelRefresh([BUILTIN_ENTRY])

    expect(keyNames(keysFor(event('log.appended', { run_id: 'r1' })))).toEqual(
      keyNames([queryKeys.log('r1'), panelQueryKey(LOG.source ?? '')]),
    )
  })
})

describe('fetchPanel', () => {
  beforeEach(() => {
    createAppQueryClient()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('asks the manifest’s URL with the scope’s parameters', async () => {
    const calls: Request[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (request: Request) => {
        calls.push(request)
        return new Response('{"metrics": []}', {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }),
    )

    await fetchPanel('/api/plugins/_builtin/overview', { run_id: 'r1' })

    expect(calls[0]?.url).toBe(
      `${window.location.origin}/api/plugins/_builtin/overview?run_id=r1`,
    )
  })

  it('turns a refusal into an error carrying the status and the code', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response('{"error": "the plugin raised", "code": "plugin_error"}', {
            status: 500,
            headers: { 'Content-Type': 'application/json' },
          }),
      ),
    )

    const failure = await fetchPanel('/api/plugins/gamedev/words', {}).catch(
      (error: unknown) => error,
    )

    expect(failure).toBeInstanceOf(PanelSourceError)
    expect((failure as PanelSourceError).status).toBe(500)
    expect((failure as PanelSourceError).code).toBe('plugin_error')
    expect((failure as PanelSourceError).message).toBe('the plugin raised')
  })
})

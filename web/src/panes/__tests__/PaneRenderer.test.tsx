/**
 * `PaneRenderer` over the manifest: what it fetches, what it draws, and
 * what it does with everything it cannot draw.
 *
 * The two builtin data panes are the ones that matter here — the
 * overview is a `dashboard` and the log is a `log`, declared on
 * `_builtin` like any plugin's (09 §Builtins are plugins) — so this
 * suite renders them from the shapes their routes answer with. What the
 * overview *draws* is `./Overview.test.tsx`; what is under test here is
 * that the host reaches it through the manifest, and appends the
 * `placement="card"` panels below it (09 §Slots).
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createAppQueryClient } from '../../api/client'
import {
  listRunsApiRunsGetQueryKey,
  manifestApiPluginsGetQueryKey,
} from '../../api/gen/@tanstack/react-query.gen'
import type { PanelOut, RunSummary } from '../../api/gen/types.gen'
import { PaneRenderer } from '../PaneRenderer'
import type { PanelScope } from '../source'
import type { Pane } from '../usePanes'
import {
  BUILTIN_ENTRY,
  GAMEDEV_ENTRY,
  MANIFEST,
  OVERVIEW_SOURCE,
  SAMPLES,
  panel,
} from './fixtures'

const RUN = '01JD5XPANERENDERER'

/** A pane of the cycle, as `panesOf` builds one. */
function paneOf(entry: PanelOut, workflow = '_builtin'): Pane {
  return {
    id: `${workflow}:${entry.name}`,
    workflow,
    name: entry.name,
    builtin: workflow === '_builtin',
    panel: entry,
  }
}

const OVERVIEW = paneOf(BUILTIN_ENTRY.panels?.[0] as PanelOut)
const LOG = paneOf(BUILTIN_ENTRY.panels?.[1] as PanelOut)
const AGENT = paneOf(BUILTIN_ENTRY.panels?.[2] as PanelOut)
const REQUESTS = paneOf(BUILTIN_ENTRY.panels?.[3] as PanelOut)
const WORDS = paneOf(GAMEDEV_ENTRY.panels?.[0] as PanelOut, 'gamedev')
const PLAYFIELD = paneOf(GAMEDEV_ENTRY.panels?.[3] as PanelOut, 'gamedev')

let queryClient: QueryClient

/** Answer every request with `body`, and record the URLs asked for. */
function stubFetch(body: unknown, status = 200) {
  const urls: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (request: Request) => {
      urls.push(request.url)
      return new Response(JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
  return urls
}

function draw(pane: Pane, scope: PanelScope = { runId: RUN }) {
  return render(
    <QueryClientProvider client={queryClient}>
      <PaneRenderer pane={pane} scope={scope} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  queryClient = createAppQueryClient()
  // One attempt: a pane that failed has to say so in the test's own
  // tick, not after the client's retry and its backoff.
  queryClient.setDefaultOptions({ queries: { retry: false } })
  // The virtualiser measures `offsetHeight`, which jsdom leaves at 0.
  Object.defineProperty(HTMLElement.prototype, 'offsetHeight', {
    configurable: true,
    get(this: HTMLElement) {
      return this.dataset['testid'] === 'log-scroller' ? 400 : 18
    },
  })
  Object.defineProperty(HTMLElement.prototype, 'scrollTo', {
    configurable: true,
    value: vi.fn(),
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('the builtin panes', () => {
  it('renders the overview from its source, with its own renderer', async () => {
    const urls = stubFetch(OVERVIEW_SOURCE)

    draw(OVERVIEW)

    // The panel is a `dashboard` in the manifest and reaches its
    // renderer through the same dispatch a plugin's would; the overview
    // has one of its own because its route sends `meta` too (15, D140).
    expect(await screen.findByTestId('pane-overview')).toBeInTheDocument()
    expect(urls[0]).toBe(
      `${window.location.origin}/api/plugins/_builtin/overview?run_id=${RUN}`,
    )
    expect(screen.getByText('612,884')).toBeInTheDocument()
    expect(screen.getByTestId('pane-renderer')).toHaveAttribute('data-kind', 'dashboard')
  })

  it('draws a plugin’s dashboard with the kind’s own renderer', async () => {
    stubFetch(SAMPLES.dashboard)

    draw(paneOf(panel({ name: 'playtest', kind: 'dashboard', source: '/x' }), 'gamedev'))

    expect(await screen.findByTestId('pane-dashboard')).toBeInTheDocument()
    expect(screen.getByText('SESSIONS')).toBeInTheDocument()
  })

  it('renders the log from its log source', async () => {
    stubFetch(SAMPLES.log)

    draw(LOG)

    expect(await screen.findByTestId('pane-log')).toBeInTheDocument()
    expect(screen.getByTestId('log-count')).toHaveTextContent('4 lines')
    expect(screen.getByText('engineering → qa')).toBeInTheDocument()
  })

  it('draws no footer on a builtin: nobody registered it', async () => {
    stubFetch(OVERVIEW_SOURCE)

    draw(OVERVIEW)
    await screen.findByTestId('pane-overview')

    expect(screen.queryByText(/registered by/)).toBeNull()
  })
})

describe('the cards under the overview', () => {
  /** The gamedev run whose workflow owns the `budget` card. */
  const RUNS: RunSummary[] = [
    {
      id: RUN,
      workflow: 'gamedev',
      title: 'squirrels vs chipmunks',
      status: 'running',
      position: 1,
      created: '2026-09-08T08:56:00Z',
      updated: '2026-09-08T09:00:00Z',
    },
  ]

  /** Answer per route, since the pane and its card ask for different data. */
  function stubRoutes(routes: Record<string, unknown>) {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (request: Request) => {
        const match = Object.entries(routes).find(([path]) => request.url.includes(path))
        return new Response(JSON.stringify(match?.[1] ?? {}), {
          status: match === undefined ? 404 : 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }),
    )
  }

  beforeEach(() => {
    queryClient.setQueryData(manifestApiPluginsGetQueryKey(), MANIFEST)
    queryClient.setQueryData(listRunsApiRunsGetQueryKey(), RUNS)
  })

  it('appends the run’s `placement=card` panels below it', async () => {
    stubRoutes({
      '_builtin/overview': OVERVIEW_SOURCE,
      'gamedev/budget': SAMPLES.kv,
    })

    draw(OVERVIEW)

    const card = await screen.findByTestId('panel-card')
    expect(card).toHaveAttribute('data-panel', 'gamedev:budget')
    // The card is a `kv` panel and draws as one; it is not a pane, so
    // the cycle is unchanged and it carries no pane footer.
    expect(await within(card).findByText('py312')).toBeInTheDocument()
    expect(screen.queryByText(/registered by/)).toBeNull()
  })

  it('draws none on a run whose workflow contributed none', async () => {
    queryClient.setQueryData(listRunsApiRunsGetQueryKey(), [
      { ...(RUNS[0] as RunSummary), workflow: 'feature_build' },
    ])
    stubRoutes({ '_builtin/overview': OVERVIEW_SOURCE })

    draw(OVERVIEW)
    await screen.findByTestId('pane-overview')

    expect(screen.queryByTestId('overview-cards')).toBeNull()
  })
})

describe('a plugin’s pane', () => {
  it('says which workflow contributed it', async () => {
    stubFetch(SAMPLES.table)

    draw(WORDS)

    expect(await screen.findByTestId('pane-table')).toBeInTheDocument()
    expect(screen.getByText(/registered by gamedev/)).toBeInTheDocument()
    expect(screen.getByTestId('pane-source')).toHaveTextContent(
      '/api/plugins/gamedev/words',
    )
  })
})

describe('what it cannot draw', () => {
  it('renders a placeholder for a kind this build does not know', () => {
    const urls = stubFetch({})
    const future = paneOf(
      panel({
        name: 'timeline',
        kind: 'timeline' as PanelOut['kind'],
        source: '/api/plugins/gamedev/timeline',
      }),
      'gamedev',
    )

    // A plugin from a newer Athanore degrades; it does not white-screen.
    expect(() => {
      draw(future)
    }).not.toThrow()
    expect(screen.getByTestId('pane-placeholder')).toHaveTextContent(
      'no renderer for a timeline panel',
    )
    // And its source is not fetched: this build does not know the shape
    // the answer would have, so there is nothing to do with it.
    expect(urls).toEqual([])
  })

  it('renders a placeholder for an element this build cannot draw', () => {
    const urls = stubFetch({})

    // `<gd-playfield>` is a plugin's own tag: it is not in the element
    // table, so it degrades to the card naming it rather than to a
    // crash, which is what T071 replaces with the manifest's assets.
    draw(PLAYFIELD)

    expect(screen.getByTestId('pane-placeholder')).toHaveTextContent('<gd-playfield>')
    expect(urls).toEqual([])
  })

  it('draws the requests pane for <ath-requests>', async () => {
    stubFetch([])

    draw(REQUESTS)

    // The run pane and its `global` inbox twin are the same tag, and a
    // tag in the element table is a pane this build draws itself (09
    // §Builtins are plugins).
    expect(await screen.findByTestId('pane-requests')).toBeInTheDocument()
    expect(screen.queryByTestId('pane-placeholder')).not.toBeInTheDocument()
  })

  it('draws the agent stream for <ath-agent-stream>', async () => {
    stubFetch({ chunks: [], last_seq: 0, live: false })

    draw(AGENT)

    // The tag is in the element table, so the pane is the transcript and
    // not the placeholder (09 §Builtins are plugins).
    expect(await screen.findByTestId('pane-agent')).toBeInTheDocument()
    expect(screen.queryByTestId('pane-placeholder')).not.toBeInTheDocument()
  })

  it('renders a placeholder for a form, naming the action', () => {
    const urls = stubFetch({})
    const form = paneOf(
      panel({ name: 'override', kind: 'form', source: 'override' }),
      'gamedev',
    )

    draw(form)

    expect(screen.getByTestId('pane-placeholder')).toHaveTextContent('action override')
    expect(urls).toEqual([])
  })

  it('renders an error card when the source answers 500', async () => {
    stubFetch({ error: 'the plugin raised', code: 'plugin_error' }, 500)

    draw(WORDS)

    const card = await screen.findByTestId('pane-error')
    expect(card).toHaveTextContent('500')
    expect(card).toHaveTextContent('the plugin raised')
    expect(card).toHaveTextContent('plugin_error')
    expect(card).toHaveTextContent('/api/plugins/gamedev/words')
  })

  it('renders an error card when the source answers the wrong shape', async () => {
    stubFetch({ rows: 'not a table' })

    draw(WORDS)

    expect(await screen.findByTestId('pane-error')).toHaveTextContent(
      'the shape a table panel needs',
    )
  })

  it('waits for a run rather than asking for a 404', () => {
    const urls = stubFetch(SAMPLES.dashboard)

    draw(OVERVIEW, {})

    expect(screen.getByRole('status')).toHaveTextContent('select a run')
    expect(urls).toEqual([])
  })
})

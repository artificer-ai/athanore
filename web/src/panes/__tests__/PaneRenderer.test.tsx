/**
 * `PaneRenderer` over the manifest: what it fetches, what it draws, and
 * what it does with everything it cannot draw.
 *
 * The two builtin data panes are the ones that matter here — the
 * overview is a `dashboard` and the log is a `log`, declared on
 * `_builtin` like any plugin's (09 §Builtins are plugins) — so this
 * suite renders them from the shapes their routes answer with.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createAppQueryClient } from '../../api/client'
import type { PanelOut } from '../../api/gen/types.gen'
import { PaneRenderer } from '../PaneRenderer'
import type { PanelScope } from '../source'
import type { Pane } from '../usePanes'
import { BUILTIN_ENTRY, GAMEDEV_ENTRY, SAMPLES, panel } from './fixtures'

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
const WORDS = paneOf(GAMEDEV_ENTRY.panels?.[0] as PanelOut, 'gamedev')

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
  it('renders the overview from its dashboard source', async () => {
    const urls = stubFetch(SAMPLES.dashboard)

    draw(OVERVIEW)

    expect(await screen.findByTestId('pane-dashboard')).toBeInTheDocument()
    expect(urls[0]).toBe(
      `${window.location.origin}/api/plugins/_builtin/overview?run_id=${RUN}`,
    )
    expect(screen.getByText('SESSIONS')).toBeInTheDocument()
    expect(screen.getByTestId('pane-renderer')).toHaveAttribute('data-kind', 'dashboard')
  })

  it('renders the log from its log source', async () => {
    stubFetch(SAMPLES.log)

    draw(LOG)

    expect(await screen.findByTestId('pane-log')).toBeInTheDocument()
    expect(screen.getByTestId('log-count')).toHaveTextContent('4 lines')
    expect(screen.getByText('engineering → qa')).toBeInTheDocument()
  })

  it('draws no footer on a builtin: nobody registered it', async () => {
    stubFetch(SAMPLES.dashboard)

    draw(OVERVIEW)
    await screen.findByTestId('pane-dashboard')

    expect(screen.queryByText(/registered by/)).toBeNull()
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

  it('renders a placeholder for a custom element, and asks for nothing', () => {
    const urls = stubFetch({})

    draw(AGENT)

    expect(screen.getByTestId('pane-placeholder')).toHaveTextContent(
      '<ath-agent-stream>',
    )
    expect(urls).toEqual([])
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

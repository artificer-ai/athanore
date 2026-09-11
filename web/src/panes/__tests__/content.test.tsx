/**
 * The kind dispatch: `renderKind` and `paneContent` (`../content.tsx`).
 *
 * `PaneRenderer.test.tsx` drives the same table through the component
 * that fetches for it, which is where the manifest, the query and the
 * cards are asserted. This suite is the table itself: both functions are
 * plain functions of `(pane, data, ctx)`, so every kind, every mismatch
 * and every state a panel can be in is one call rather than a mount with
 * a network around it — which is what makes it affordable to assert all
 * of them rather than a representative few.
 *
 * The two promises 09 makes are what it is strict about:
 *
 * - **no kind is ever a crash.** An unknown kind, an unknown element, a
 *   `source` that answered the wrong shape and a `custom` panel with no
 *   element are four cards, not four exceptions.
 * - **`scrolls` is part of the answer.** Whether a kind brings its own
 *   viewport decides whether the host wraps it in a second one, and a
 *   renderer that virtualises inside a scroller that never ends measures
 *   nothing — so it is asserted beside the element, not left implied.
 */
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { describe, expect, it } from 'vitest'

import type { PanelOut } from '../../api/gen/types.gen'
import { paneContent, renderKind, type Content, type RenderContext } from '../content'
import { PanelSourceError, type PanelParams } from '../source'
import type { Pane } from '../usePanes'
import { EVENT_LOG, SAMPLES, panel } from './fixtures'

const RUN = '01JD5XCONTENT00000000000'

/**
 * A kind or a scope named as a string.
 *
 * `it.each` widens a literal to `string`, and two of the cases below are
 * deliberately values the contract does not carry — a `gantt` panel is
 * what a plugin built against a later Athanore declares, and drawing a
 * card for it rather than crashing is the thing under test (09 §Panel
 * kinds).
 */
const asKind = (kind: string) => kind as PanelOut['kind']
const asScope = (scope: string) => scope as PanelOut['scope']

/** A pane of the cycle, over the panel entry `over` describes. */
function paneOf(over: Partial<PanelOut> & { name: string }, workflow = 'gamedev'): Pane {
  const entry = panel(over)
  return {
    id: `${workflow}:${entry.name}`,
    workflow,
    name: entry.name,
    builtin: workflow === '_builtin',
    panel: entry,
  }
}

/** The context a run-scoped panel is drawn in. */
const CTX: RenderContext = { scope: { runId: RUN } }

/** A query that answered with `data`. */
function answered(data: unknown) {
  return { isPending: false, isError: false, error: null, data }
}

/**
 * Draw a {@link Content}. The three element renderers mount queries of
 * their own, so the provider is here rather than in each test.
 */
function draw(content: Content): ReactNode {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, enabled: false } },
  })
  render(
    <QueryClientProvider client={queryClient}>{content.node}</QueryClientProvider>,
  )
  return content.node
}

describe('renderKind', () => {
  describe('the data kinds', () => {
    it.each([
      ['markdown', SAMPLES.markdown, false],
      ['kv', SAMPLES.kv, false],
      ['table', SAMPLES.table, false],
      ['log', SAMPLES.log, true],
      ['chart', SAMPLES.chart, false],
      ['dashboard', SAMPLES.dashboard, false],
    ])('draws a %s panel from 09’s own sample', (kind, data, scrolls) => {
      const content = renderKind(paneOf({ name: kind, kind: asKind(kind) }), data, CTX)

      draw(content)
      expect(content.scrolls).toBe(scrolls)
      // Whatever it drew, it is not the card that says it could not.
      expect(screen.queryByTestId('pane-error')).toBeNull()
      expect(screen.queryByTestId('pane-placeholder')).toBeNull()
    })

    it.each(['markdown', 'kv', 'table', 'log', 'chart', 'dashboard'])(
      'answers a %s panel whose source sent the wrong shape with an error card',
      (kind) => {
        // A number is none of the six shapes 09 declares.
        const content = renderKind(
          paneOf({
            name: kind,
            kind: asKind(kind),
            source: `/api/plugins/gamedev/${kind}`,
          }),
          17,
          CTX,
        )

        draw(content)
        expect(content.scrolls).toBe(false)
        const card = screen.getByTestId('pane-error')
        expect(card).toHaveTextContent(`the shape a ${kind} panel needs`)
        // The URL that sent it, so the operator knows whose fault it is.
        expect(card).toHaveTextContent(`/api/plugins/gamedev/${kind}`)
      },
    )

    it('names no source on a mismatch from a panel that declares none', () => {
      const content = renderKind(paneOf({ name: 'kv', kind: 'kv' }), 17, CTX)

      draw(content)
      expect(screen.getByTestId('pane-error')).not.toHaveTextContent('/api/')
    })
  })

  describe('the builtin panels', () => {
    it('draws the overview with its own renderer, not the dashboard kind', () => {
      const content = renderKind(
        paneOf({ name: 'overview', kind: 'dashboard' }, '_builtin'),
        { ...SAMPLES.dashboard, meta: { RUN, WORKFLOW: 'gamedev' } },
        { ...CTX, cards: <p>a card of the run’s workflow</p> },
      )

      draw(content)
      // `meta` is the fourth key the overview's route sends (D140) and
      // the grid the plain `dashboard` renderer has no row for.
      expect(screen.getByText('WORKFLOW')).toBeInTheDocument()
      expect(screen.getByText('a card of the run’s workflow')).toBeInTheDocument()
      expect(content.scrolls).toBe(true)
    })

    it('falls back to the mismatch card when the overview route drifts', () => {
      const content = renderKind(
        paneOf({ name: 'overview', kind: 'dashboard' }, '_builtin'),
        { metrics: 'not a list' },
        CTX,
      )

      draw(content)
      expect(screen.getByTestId('pane-error')).toBeInTheDocument()
    })

    it('draws the event log with the pane 10 §Panes item 2 asks for', () => {
      const content = renderKind(
        paneOf(
          { name: 'log', kind: 'log', source: '/api/plugins/_builtin/log' },
          '_builtin',
        ),
        EVENT_LOG,
        { ...CTX, node: 'qa', onFilterNode: () => {} },
      )

      draw(content)
      expect(content.scrolls).toBe(true)
      // The header, the `?node=` filter and the count of what the filter
      // left are the builtin pane's; a plugin's `log` is a list of lines
      // and has none of them (10 §Panes item 2).
      expect(screen.getByText('EVENT LOG')).toBeInTheDocument()
      expect(screen.getByTestId('log-node-filter')).toHaveTextContent('qa')
      expect(screen.getByTestId('log-count')).toHaveTextContent('1 lines')
    })

    it('falls back to the mismatch card when the log route drifts', () => {
      const content = renderKind(
        paneOf({ name: 'log', kind: 'log' }, '_builtin'),
        { rows: [] },
        CTX,
      )

      draw(content)
      expect(screen.getByTestId('pane-error')).toBeInTheDocument()
    })

    it('sends another server’s panel of the same name to the kind’s renderer', () => {
      // `BUILTIN_RENDERERS` is keyed by the name *on `_builtin`*: a
      // plugin's own `overview` is a dashboard like any other.
      const content = renderKind(
        paneOf({ name: 'overview', kind: 'dashboard' }, 'gamedev'),
        SAMPLES.dashboard,
        CTX,
      )

      draw(content)
      expect(screen.getByText('SESSIONS')).toBeInTheDocument()
      expect(content.scrolls).toBe(false)
    })
  })

  describe('the custom elements', () => {
    it.each([
      ['ath-agent-stream', 'agent'],
      ['ath-requests', 'requests'],
      ['ath-run-graph', 'graph'],
    ])('draws <%s> from this build’s own bundle', (element, name) => {
      const content = renderKind(
        paneOf({ name, kind: 'custom', element }, '_builtin'),
        undefined,
        { ...CTX, scope: { runId: RUN, taskId: 405 } },
      )

      draw(content)
      // Each brings its own header and its own scroller, so the host
      // must not wrap it in a second one.
      expect(content.scrolls).toBe(true)
      expect(screen.queryByTestId('pane-placeholder')).toBeNull()
    })

    it('sends a tag this build does not draw to the element host', () => {
      // Its workflow ships no assets here, so the host says what it is
      // waiting for; `CustomElementHost.test.tsx` mounts the tag for
      // real (09 §Escape hatch).
      const content = renderKind(
        paneOf({ name: 'playfield', kind: 'custom', element: 'gd-playfield' }),
        undefined,
        CTX,
      )

      draw(content)
      expect(content.scrolls).toBe(false)
      expect(screen.getByTestId('pane-placeholder')).toHaveTextContent('<gd-playfield>')
    })

    it('renders a placeholder for a custom panel that named no element', () => {
      const content = renderKind(paneOf({ name: 'nameless', kind: 'custom' }), undefined, CTX)

      draw(content)
      expect(screen.getByTestId('pane-placeholder')).toHaveTextContent(
        'this custom panel names no element',
      )
    })
  })

  describe('the form kind', () => {
    it('hands a form panel to the action its source names', () => {
      const content = renderKind(
        paneOf({ name: 'approve', kind: 'form', source: 'approve' }),
        undefined,
        CTX,
      )

      draw(content)
      // The schema comes from the manifest and this suite draws without
      // one, so what shows is the pane waiting for it. That the dispatch
      // reaches the runner at all is what is under test here; the form,
      // the confirm and the POST are `Form.test.tsx`'s.
      expect(content.scrolls).toBe(false)
      expect(screen.getByRole('status')).toHaveTextContent('loading approve')
    })

    it('says so plainly for a form panel that named no action', () => {
      const content = renderKind(paneOf({ name: 'approve', kind: 'form' }), undefined, CTX)

      draw(content)
      expect(screen.getByTestId('pane-placeholder')).toHaveTextContent(
        'this form panel names no action',
      )
    })
  })

  describe('the kinds with no renderer yet', () => {
    it('degrades an unknown kind to a card that names its plugin', () => {
      // 09 §Panel kinds: "Unknown `kind` renders a placeholder card,
      // never a crash" — a plugin built against a later Athanore.
      const content = renderKind(
        paneOf({ name: 'timeline', kind: asKind('gantt') }),
        undefined,
        CTX,
      )

      draw(content)
      expect(content.scrolls).toBe(false)
      const card = screen.getByTestId('pane-placeholder')
      expect(card).toHaveTextContent('no renderer for a gantt panel')
      expect(card).toHaveTextContent('declared by gamedev, a plugin of this server')
    })

    it('says the core declared one this build cannot draw', () => {
      const content = renderKind(
        paneOf({ name: 'timeline', kind: asKind('gantt') }, '_builtin'),
        undefined,
        CTX,
      )

      draw(content)
      expect(screen.getByTestId('pane-placeholder')).toHaveTextContent('declared by the core')
    })
  })
})

describe('paneContent', () => {
  const PARAMS: PanelParams = { run_id: RUN }
  const SOURCE = '/api/plugins/gamedev/words'

  it('draws a kind with no data from the manifest entry alone', () => {
    // `custom`, `form` and the unknown kinds are never fetched
    // (`source.ts`, `DATA_KINDS`), so the query is not consulted.
    const content = paneContent(
      paneOf({ name: 'playfield', kind: 'custom', element: 'gd-playfield' }),
      null,
      { isPending: true, isError: true, error: new Error('never asked'), data: undefined },
      CTX,
    )

    draw(content)
    expect(screen.getByTestId('pane-placeholder')).toHaveTextContent('<gd-playfield>')
  })

  it('says so when a data panel declares no source at all', () => {
    // Registration refuses one (09 §Registration and validation, rule
    // 4), so this is a server this build was not written for.
    const content = paneContent(
      paneOf({ name: 'words', kind: 'table' }),
      PARAMS,
      answered(SAMPLES.table),
      CTX,
    )

    draw(content)
    expect(screen.getByTestId('pane-placeholder')).toHaveTextContent(
      'this table panel declares no source',
    )
    expect(screen.getByTestId('pane-placeholder')).toHaveTextContent('registered by gamedev')
  })

  it.each([
    ['run', 'select a run to load this panel'],
    ['task', 'select a task to load this panel'],
    ['node', 'this panel follows a node its run has not named'],
    ['workflow', 'this panel has no scope to load in'],
  ])('says what a %s-scoped panel is waiting for rather than asking', (scope, said) => {
    const content = paneContent(
      paneOf({ name: 'words', kind: 'table', scope: asScope(scope), source: SOURCE }),
      null,
      { isPending: true, isError: false, error: null, data: undefined },
      { scope: {} },
    )

    draw(content)
    expect(screen.getByRole('status')).toHaveTextContent(said)
    expect(content.scrolls).toBe(false)
  })

  it('names the panel it is loading', () => {
    const content = paneContent(
      paneOf({ name: 'words', kind: 'table', source: SOURCE }),
      PARAMS,
      { isPending: true, isError: false, error: null, data: undefined },
      CTX,
    )

    draw(content)
    expect(screen.getByRole('status')).toHaveTextContent('loading words…')
  })

  it('shows the status, the code and the URL a refused source answered with', () => {
    const content = paneContent(
      paneOf({ name: 'words', kind: 'table', source: SOURCE }),
      PARAMS,
      {
        isPending: false,
        isError: true,
        error: new PanelSourceError('the panel raised', 500, 'internal_error'),
        data: undefined,
      },
      CTX,
    )

    draw(content)
    const card = screen.getByTestId('pane-error')
    expect(card).toHaveTextContent('500 · this panel failed to load')
    expect(card).toHaveTextContent('the panel raised')
    expect(card).toHaveTextContent('internal_error')
    expect(card).toHaveTextContent(SOURCE)
  })

  it('shows what it can of a failure that was not the source’s own', () => {
    const content = paneContent(
      paneOf({ name: 'words', kind: 'table', source: SOURCE }),
      PARAMS,
      { isPending: false, isError: true, error: new Error('network down'), data: undefined },
      CTX,
    )

    draw(content)
    const card = screen.getByTestId('pane-error')
    expect(card).toHaveTextContent('this panel failed to load')
    expect(card).toHaveTextContent('network down')
  })

  it('says the request failed for a rejection that was not an Error', () => {
    const content = paneContent(
      paneOf({ name: 'words', kind: 'table', source: SOURCE }),
      PARAMS,
      { isPending: false, isError: true, error: 'nothing usable', data: undefined },
      CTX,
    )

    draw(content)
    expect(screen.getByTestId('pane-error')).toHaveTextContent('the request failed')
  })

  it('renders the kind once the data has arrived', () => {
    const content = paneContent(
      paneOf({ name: 'words', kind: 'table', source: SOURCE }),
      PARAMS,
      answered(SAMPLES.table),
      CTX,
    )

    draw(content)
    expect(screen.getByRole('columnheader', { name: 'SESSION' })).toBeInTheDocument()
  })
})

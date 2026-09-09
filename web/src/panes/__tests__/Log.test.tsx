/**
 * The event log pane: what it draws from the builtin's merged list, what
 * `?node=` narrows it to, and what the composer does with a note
 * (`docs/v1/10-frontend.md` §Panes item 2).
 *
 * The rows are the route's own answer (`./fixtures.ts`, `EVENT_LOG`),
 * narrowed by `asLog` exactly as the pane host narrows it, so what is
 * under test is the pane and never a shape invented here. The run is
 * seeded into the cache rather than fetched: the header's `● tailing` /
 * `○ complete` is the run's status, and what matters is which word it
 * draws for which status.
 *
 * The composer is the one thing in this pane that writes. Both halves of
 * it are tested — the note that lands clears the box, and the note that
 * is refused stays in it with the refusal beside it, because the
 * operator wrote it and this is the only copy.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createAppQueryClient } from '../../api/client'
import { listRunsApiRunsGetQueryKey } from '../../api/gen/@tanstack/react-query.gen'
import type { RunStatus } from '../../api/gen/types.gen'
import { useUi } from '../../store/ui'
import {
  Log,
  appendError,
  asLog,
  isProse,
  logAuthor,
  logLines,
  type LogRow,
} from '../kinds'
import { panelQueryKey } from '../source'
import { EVENT_LOG, LOG_RUN, logRun } from './fixtures'

/** The builtin log panel's route, which is also its cache key. */
const SOURCE = '/api/plugins/_builtin/log'

let queryClient: QueryClient

/** The fixture, narrowed the way the pane host narrows it. */
function rows(data: unknown = EVENT_LOG): LogRow[] {
  const narrowed = asLog(data)
  if (narrowed === null) throw new Error('the event log fixture no longer narrows')
  return narrowed
}

/** Answer every request with `body`, and record what was asked. */
function stubFetch(body: unknown, status = 200) {
  const calls: { url: string; method: string; body: unknown }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (request: Request) => {
      calls.push({
        url: request.url,
        method: request.method,
        body: await request
          .clone()
          .json()
          .catch(() => undefined),
      })
      return new Response(JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
  return calls
}

function draw(
  options: {
    data?: LogRow[]
    status?: RunStatus
    node?: string
    onFilterNode?: (node: string | undefined) => void
  } = {},
) {
  queryClient.setQueryData(listRunsApiRunsGetQueryKey(), [logRun(options.status)])
  return render(
    <QueryClientProvider client={queryClient}>
      <Log
        data={options.data ?? rows()}
        runId={LOG_RUN}
        source={SOURCE}
        {...(options.node === undefined ? {} : { node: options.node })}
        {...(options.onFilterNode === undefined
          ? {}
          : { onFilterNode: options.onFilterNode })}
      />
    </QueryClientProvider>,
  )
}

/** The pane over the fixture, with whatever run list the test seeded. */
function drawWithoutSeeding() {
  return render(
    <QueryClientProvider client={queryClient}>
      <Log data={rows()} runId={LOG_RUN} source={SOURCE} />
    </QueryClientProvider>,
  )
}

/** The message cells, in the order they are drawn. */
function messages() {
  return screen.getAllByTestId('log-message')
}

beforeEach(() => {
  queryClient = createAppQueryClient()
  // The seeded run list is the whole of what this pane reads: kept
  // fresh, nothing here reaches for it over the network.
  queryClient.setDefaultOptions({ queries: { retry: false, staleTime: Infinity } })
  // jsdom performs no layout and the virtualiser measures the DOM: a
  // 400 px scroller over 18 px rows, as the other pane suites state it.
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
  stubFetch({ log_id: 91 })
  useUi.setState({ logComposerFor: null })
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('the header', () => {
  it('is the mock’s: the pane, the count, and a running run tailing', () => {
    draw()

    expect(screen.getByText('EVENT LOG')).toBeInTheDocument()
    expect(screen.getByTestId('log-count')).toHaveTextContent('5 lines')
    expect(screen.getByTestId('log-state')).toHaveTextContent('● tailing')
  })

  it('reads ○ complete for a run that is producing nothing more', () => {
    draw({ status: 'completed' })

    expect(screen.getByTestId('log-state')).toHaveTextContent('○ complete')
  })

  it('says nothing about tailing while the run’s status has not arrived', () => {
    // The run list is still in flight. Neither word is true yet, and
    // AGENTS.md's "unknown is omitted" makes ○ complete the wrong
    // default: a deep link to a running run would read as finished.
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise<Response>(() => {})),
    )
    drawWithoutSeeding()

    expect(screen.getByText('EVENT LOG')).toBeInTheDocument()
    expect(screen.queryByTestId('log-state')).not.toBeInTheDocument()
  })

  it('says nothing about tailing for a run the list does not carry', () => {
    queryClient.setQueryData(listRunsApiRunsGetQueryKey(), [])
    drawWithoutSeeding()

    expect(screen.queryByTestId('log-state')).not.toBeInTheDocument()
  })

  it('counts the lines it is showing, not the ones it was given', () => {
    draw({ node: 'qa' })

    expect(screen.getByTestId('log-count')).toHaveTextContent('1 lines')
  })
})

describe('the rows', () => {
  it('draws both sources in time order, whatever order they arrived in', () => {
    draw()

    // `run.created` is last in the route's array and first in time; the
    // work log's entries and the engine's events interleave after it.
    expect(messages().map((row) => row.textContent)).toEqual([
      'run created in feature_build at position 1',
      'architecture → engineering',
      'report\nwrote the pane host',
      '[stats] 12,480 tokens · $0.03 · 41.2s',
      'looks right to me',
    ])
  })

  it('keeps a row whose ts is not a time where its source put it', () => {
    // The unparseable row holds its own position — second of five — and
    // holds nothing else: the four timed rows fill the four remaining
    // positions in time order, across it.
    const broken: LogRow[] = [
      { ts: '2026-09-08T09:00:05Z', text: 'fifth' },
      { ts: 'not a time', text: 'unparseable' },
      { ts: '2026-09-08T09:00:01Z', text: 'first' },
      { ts: '2026-09-08T09:00:03Z', text: 'third' },
      { ts: '2026-09-08T09:00:02Z', text: 'second' },
    ]

    expect(logLines(broken).map((row) => row.text)).toEqual([
      'first',
      'unparseable',
      'second',
      'third',
      'fifth',
    ])
  })

  it('orders the same rows the same way however many surround them', () => {
    // The comparator is consistent, so a bad row cannot make the answer
    // depend on the array's length (an inconsistent one leaves
    // `Array.prototype.sort` implementation-defined, and V8 switches
    // algorithm at 22 elements).
    const pad = (n: number): LogRow => ({
      ts: `2026-09-08T10:00:${String(n).padStart(2, '0')}Z`,
      text: `pad ${n}`,
    })
    const three: LogRow[] = [
      { ts: '2026-09-08T09:00:02Z', text: 'second' },
      { ts: 'not a time', text: 'unparseable' },
      { ts: '2026-09-08T09:00:01Z', text: 'first' },
    ]

    expect(logLines(three).map((row) => row.text)).toEqual([
      'first',
      'unparseable',
      'second',
    ])
    expect(
      logLines([...three, ...Array.from({ length: 30 }, (_, i) => pad(i))])
        .map((row) => row.text)
        .slice(0, 3),
    ).toEqual(['first', 'unparseable', 'second'])
  })

  it('keeps rows of the same instant in the order their source sent them', () => {
    const tied: LogRow[] = [
      { ts: '2026-09-08T09:00:01Z', text: 'the entry' },
      { ts: '2026-09-08T09:00:01Z', text: 'the event announcing it' },
    ]

    expect(logLines(tied).map((row) => row.text)).toEqual([
      'the entry',
      'the event announcing it',
    ])
  })

  it('draws the time and the node/author source of every line', () => {
    draw()

    expect(screen.getByText('engineering/agent')).toBeInTheDocument()
    expect(screen.getByText('qa/user')).toBeInTheDocument()
    // The lifecycle event whose payload named no node is the engine's.
    expect(screen.getByText('engine')).toBeInTheDocument()
  })

  it('colours each line with the tone its author gave it', () => {
    draw()

    const [created, edge, report, stats, note] = messages()
    // dim: the engine, and every lifecycle event.
    expect(created?.className).toContain('text-muted-foreground')
    expect(edge?.className).toContain('text-muted-foreground')
    // accent: the stats lines, the mock's "tool lines".
    expect(stats?.className).toContain('text-[var(--color-accent-300)]')
    // default: what an agent or a person wrote.
    expect(report?.className).toContain('text-[var(--color-neutral-300)]')
    expect(note?.className).toContain('text-[var(--color-neutral-300)]')
  })

  it('renders markdown for an agent and a person, and for nobody else', () => {
    draw()

    const [created, , report, stats, note] = messages()

    expect(report).toHaveAttribute('data-markdown', 'true')
    expect(within(report as HTMLElement).getByRole('heading')).toHaveTextContent(
      'report',
    )
    expect(report?.querySelector('strong')).toHaveTextContent('pane host')

    expect(note).toHaveAttribute('data-markdown', 'true')
    expect(note?.querySelector('em')).toHaveTextContent('right')

    // The engine's lines are the text they are: an engine message
    // cannot smuggle formatting into the pane (10 §Panes).
    expect(created).toHaveAttribute('data-markdown', 'false')
    expect(stats).toHaveAttribute('data-markdown', 'false')
  })

  it('reads the author out of the source column, and nowhere else', () => {
    expect(logAuthor({ ts: '', text: '', source: 'engineering/agent' })).toBe('agent')
    expect(logAuthor({ ts: '', text: '', source: 'engine' })).toBe('engine')
    expect(logAuthor({ ts: '', text: '' })).toBeUndefined()
    // A plugin's own `log` rows carry no author, so none of them is prose.
    expect(isProse({ ts: '', text: '' })).toBe(false)
  })
})

describe('the ?node= filter', () => {
  it('draws that node’s entries and events, and no others', () => {
    draw({ node: 'engineering' })

    expect(messages().map((row) => row.textContent)).toEqual([
      'architecture → engineering',
      'report\nwrote the pane host',
      '[stats] 12,480 tokens · $0.03 · 41.2s',
    ])
    // `run.created` names no node, so it belongs to none of them.
    expect(screen.queryByText(/run created/)).not.toBeInTheDocument()
  })

  it('clears itself through the search parameter that set it', async () => {
    const user = userEvent.setup()
    const onFilterNode = vi.fn()
    draw({ node: 'engineering', onFilterNode })

    const chip = screen.getByTestId('log-node-filter')
    expect(chip).toHaveTextContent('node engineering')

    await user.click(chip)

    expect(onFilterNode).toHaveBeenCalledWith(undefined)
  })

  it('says which node it found nothing under', () => {
    draw({ node: 'review' })

    expect(screen.getByRole('status')).toHaveTextContent('nothing logged under review')
    expect(screen.getByTestId('log-count')).toHaveTextContent('0 lines')
  })

  it('draws no filter chip when nothing is filtered', () => {
    draw()

    expect(screen.queryByTestId('log-node-filter')).not.toBeInTheDocument()
  })
})

describe('the composer', () => {
  it('posts the note to the run’s log and clears the box', async () => {
    const user = userEvent.setup()
    const calls = stubFetch({ log_id: 91 })
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')
    draw()

    const box = screen.getByLabelText('append a note to the work log')
    await user.type(box, 'rerun this once the gate is green')
    await user.click(screen.getByTestId('log-append'))

    await waitFor(() => {
      expect(box).toHaveValue('')
    })
    expect(calls).toHaveLength(1)
    expect(calls[0]?.method).toBe('POST')
    expect(calls[0]?.url).toBe(
      `${window.location.origin}/api/runs/${LOG_RUN}/log`,
    )
    expect(calls[0]?.body).toEqual({ text: 'rerun this once the gate is green' })
    // The operator's own note appears whether or not this tab's feed is
    // up, so the panel's query is invalidated by the write as well.
    expect(invalidate).toHaveBeenCalledWith({ queryKey: panelQueryKey(SOURCE) })
  })

  it('sends on ⌘⏎ as well as on the button', async () => {
    const user = userEvent.setup()
    const calls = stubFetch({ log_id: 92 })
    draw()

    const box = screen.getByLabelText('append a note to the work log')
    await user.type(box, 'noted{Meta>}{Enter}{/Meta}')

    await waitFor(() => {
      expect(calls).toHaveLength(1)
    })
    expect(calls[0]?.body).toEqual({ text: 'noted' })
  })

  it('keeps the note and says why when the post is refused', async () => {
    const user = userEvent.setup()
    stubFetch({ error: 'that run is gone', code: 'not_found' }, 404)
    draw()

    const box = screen.getByLabelText('append a note to the work log')
    await user.type(box, 'still here')
    await user.click(screen.getByTestId('log-append'))

    expect(await screen.findByRole('alert')).toHaveTextContent('that run is gone')
    expect(box).toHaveValue('still here')
  })

  it('takes the caret when append log asks for this run', async () => {
    draw()
    const box = screen.getByLabelText('append a note to the work log')
    expect(box).not.toHaveFocus()

    // The palette's `append log` (`overlays/actions.ts`), reaching the
    // box the pane owns: the shell shows the log pane and asks, and the
    // composer is what puts the caret in itself.
    act(() => {
      useUi.getState().focusLogComposer(LOG_RUN)
    })

    await waitFor(() => {
      expect(box).toHaveFocus()
    })
    // Served once: the request is gone, so a later remount of this pane
    // does not take the caret again.
    expect(useUi.getState().logComposerFor).toBeNull()
  })

  it('takes a request made before the pane was drawn', async () => {
    // Which is the ordinary case: the command moves the pane cycle, and
    // the pane draws its composer a render later, once its panel has
    // answered.
    useUi.setState({ logComposerFor: LOG_RUN })
    draw()

    await waitFor(() => {
      expect(screen.getByLabelText('append a note to the work log')).toHaveFocus()
    })
    expect(useUi.getState().logComposerFor).toBeNull()
  })

  it('leaves a request made for another run alone', () => {
    useUi.setState({ logComposerFor: 'ffff9999eeee' })
    draw()

    expect(screen.getByLabelText('append a note to the work log')).not.toHaveFocus()
    expect(useUi.getState().logComposerFor).toBe('ffff9999eeee')
  })

  it('will not post an empty note', async () => {
    const user = userEvent.setup()
    const calls = stubFetch({ log_id: 93 })
    draw()

    const box = screen.getByLabelText('append a note to the work log')
    await user.type(box, '   ')

    expect(screen.getByTestId('log-append')).toBeDisabled()
    await user.click(screen.getByTestId('log-append'))
    expect(calls).toHaveLength(0)
  })
})

/**
 * What the composer says when the note was refused. The generated client
 * throws the parsed body — `{error, code}` (08 §Conventions) — rather
 * than an `Error`, so both are read and neither is assumed, and the
 * fallback exists because the operator wrote that note and this is the
 * only copy of it.
 */
describe('a refused note', () => {
  it('reads the API’s one error shape', () => {
    expect(appendError({ error: 'the run has ended', code: 'conflict' })).toBe(
      'the run has ended',
    )
  })

  it('reads an Error, which is what a transport failure is', () => {
    expect(appendError(new TypeError('Failed to fetch'))).toBe('Failed to fetch')
  })

  it('reads a bare string', () => {
    expect(appendError('502 Bad Gateway')).toBe('502 Bad Gateway')
  })

  it.each([
    ['nothing at all', undefined],
    ['an empty body', {}],
    ['an empty message', { error: '' }],
    ['an Error with no message', new Error('')],
    ['whitespace', '   '],
  ])('falls back for %s rather than saying nothing', (_case, thrown) => {
    expect(appendError(thrown)).toBe('the note was not appended')
  })
})

/**
 * The agent pane: which attempt it follows, what one chunk becomes, and
 * how a chunk that arrives while it is open reaches it
 * (`docs/v1/10-frontend.md` §Panes item 3 and §Plugin renderers).
 *
 * The third of those is the point of the task and is asserted on the
 * **request**, not on the output: a pane that refetched the whole
 * transcript on every `task.stream` event would render the same text and
 * cost the run's entire history two or three times a second. So the
 * suite drives a real `Invalidator` over the cache the pane filled and
 * looks at what went out on the wire.
 *
 * The other request the pane makes is the one the endpoint's page size
 * forces: `GET /api/tasks/{id}/stream` answers with at most 500 chunks
 * and says where the transcript really ends, so the paging cases stand a
 * server up that honours `?after=` and assert that the pane reads to
 * `last_seq` — a transcript drawn one page short would look complete.
 *
 * The transcript is `./fixtures.ts`'s, which carries one chunk of every
 * `ChunkKind` (03 §StreamChunk) in the order the façade writes them.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createAppQueryClient } from '../../api/client'
import {
  getRequestsApiRunsRunIdRequestsGetQueryKey,
  getRunApiRunsRunIdGetQueryKey,
} from '../../api/gen/@tanstack/react-query.gen'
import type {
  RequestView,
  RunDetail,
  StreamChunk,
  StreamOut,
} from '../../api/gen/types.gen'
import { Invalidator, queryKeys } from '../../realtime/invalidate'
import { AgentStream, blockKind, chunkLabel, focusedTask, streamBlocks } from '../kinds'
import {
  STREAM_RUN,
  STREAM_TASK,
  TRANSCRIPT,
  request,
  streamPage,
  streamRun,
} from './fixtures'

let queryClient: QueryClient

/**
 * Answer every request with `answer`, and record the URLs asked for.
 *
 * `answer` may be a function of the URL, which is how the paging cases
 * stand a server up: the endpoint's answer depends on `?after=`, and a
 * stub that ignored the cursor could not tell a pane that pages from one
 * that asks for the same page twice.
 */
function stubFetch(answer: unknown, status = 200) {
  const urls: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (request: Request) => {
      urls.push(request.url)
      const body =
        typeof answer === 'function'
          ? (answer as (url: string) => unknown)(request.url)
          : answer
      return new Response(JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
  return urls
}

/**
 * The pane over a seeded run detail and a seeded request list, so only
 * the transcript is fetched.
 *
 * The requests are seeded and not stubbed for the same reason the detail
 * is: the docked request panel reads `GET /api/runs/{id}/requests` (10
 * §Panes item 3), and every assertion below about *what went out on the
 * wire* is about the transcript. A run with no open requests is the
 * default, which is the state every case but the dock's is in.
 */
function draw(
  options: {
    detail?: RunDetail | null
    taskId?: number
    runId?: string | undefined
    requests?: RequestView[]
  } = {},
) {
  const detail = options.detail === undefined ? streamRun() : options.detail
  if (detail !== null) {
    queryClient.setQueryData(
      getRunApiRunsRunIdGetQueryKey({ path: { run_id: STREAM_RUN } }),
      detail,
    )
  }
  queryClient.setQueryData(
    getRequestsApiRunsRunIdRequestsGetQueryKey({ path: { run_id: STREAM_RUN } }),
    options.requests ?? [],
  )
  return render(
    <QueryClientProvider client={queryClient}>
      <AgentStream
        runId={'runId' in options ? options.runId : STREAM_RUN}
        {...(options.taskId === undefined ? {} : { taskId: options.taskId })}
      />
    </QueryClientProvider>,
  )
}

/** The blocks in the order they are drawn. */
function blocks() {
  return screen.getAllByTestId('stream-block')
}

beforeEach(() => {
  queryClient = createAppQueryClient()
  // What is seeded is kept: nothing here refetches the run detail.
  queryClient.setDefaultOptions({ queries: { retry: false, staleTime: Infinity } })
  // jsdom performs no layout and the virtualiser measures the DOM: a
  // 400 px scroller over 60 px blocks, as the other pane suites state it.
  Object.defineProperty(HTMLElement.prototype, 'offsetHeight', {
    configurable: true,
    get(this: HTMLElement) {
      return this.dataset['testid'] === 'stream-scroller' ? 400 : 60
    },
  })
  Object.defineProperty(HTMLElement.prototype, 'scrollTo', {
    configurable: true,
    value: vi.fn(),
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

/* -------------------------------------------------------------------- */
/* The docked request panel                                              */
/* -------------------------------------------------------------------- */

describe('the docked request panel', () => {
  /** An open question raised by the attempt the pane is following. */
  function openOn(taskId: number, over: Partial<RequestView> = {}) {
    return request({
      id: 71,
      run_id: STREAM_RUN,
      task_id: taskId,
      node: 'engineering',
      source: 'agent',
      kind: 'permission',
      mode: 'options',
      prompt: 'permission: run the gate',
      options: [
        { option_id: 'allow_once', name: 'Allow once', kind: 'allow_once' },
        { option_id: 'reject_once', name: 'Reject', kind: 'reject_once' },
      ],
      pending: true,
      ...over,
    })
  }

  it('docks under the stream when the focused task has an open request', async () => {
    stubFetch(streamPage())

    draw({ requests: [openOn(STREAM_TASK)] })

    const dock = await screen.findByTestId('stream-request-dock')
    expect(dock).toHaveTextContent('WAITING ON YOU')
    expect(within(dock).getByTestId('request-prompt')).toHaveTextContent(
      'permission: run the gate',
    )
    // The controls are the same panel the requests pane draws.
    expect(within(dock).getAllByTestId('request-option')).toHaveLength(2)
  })

  it('draws no dock for a request of another attempt, or an answered one', async () => {
    stubFetch(streamPage())

    draw({
      requests: [
        openOn(406),
        openOn(STREAM_TASK, { id: 72, answer: 'allow_once', answered_by: 'user' }),
      ],
    })

    await screen.findByTestId('stream-scroller')
    expect(screen.queryByTestId('stream-request-dock')).not.toBeInTheDocument()
  })

  it('counts them when one turn asked more than once', async () => {
    stubFetch(streamPage())

    draw({
      requests: [openOn(STREAM_TASK), openOn(STREAM_TASK, { id: 72 })],
    })

    const dock = await screen.findByTestId('stream-request-dock')
    expect(dock).toHaveTextContent('WAITING ON YOU · 2 REQUESTS')
    expect(within(dock).getAllByTestId('request-card')).toHaveLength(2)
  })
})

/* -------------------------------------------------------------------- */
/* The mapping                                                           */
/* -------------------------------------------------------------------- */

describe('the chunk mapping', () => {
  it('maps every kind onto the block 10 gives it', () => {
    expect(blockKind('notice')).toBe('system')
    expect(blockKind('text')).toBe('assistant')
    expect(blockKind('thought')).toBe('assistant')
    expect(blockKind('tool_call')).toBe('tool')
    expect(blockKind('tool_result')).toBe('tool')
  })

  it('draws a kind this build has no rule for rather than dropping it', () => {
    // A transcript written by a later Athanore: the text is still the
    // agent's, so it lands in the neutral block under its own name.
    expect(blockKind('reasoning_summary')).toBe('system')
    expect(chunkLabel('reasoning_summary')).toBe('reasoning_summary')
  })

  it('names the chunk only where the block label would lose it', () => {
    expect(chunkLabel('notice')).toBe('')
    expect(chunkLabel('text')).toBe('')
    expect(chunkLabel('thought')).toBe('thought')
    expect(chunkLabel('tool_call')).toBe('tool call')
    expect(chunkLabel('tool_result')).toBe('tool result')
  })

  it('joins the fragments of one message and keeps the rest apart', () => {
    const built = streamBlocks(TRANSCRIPT)

    expect(built.map((block) => block.chunk)).toEqual([
      'notice',
      'thought',
      'tool_call',
      'tool_result',
      'text',
    ])
    // The two `text` fragments are one paragraph…
    expect(built.at(-1)?.text).toBe(
      'Tests pass (14 passed). Pane state is now a single index.',
    )
    // …and the tool call and its result are still two blocks, both tool.
    expect(built.slice(2, 4).map((block) => block.kind)).toEqual(['tool', 'tool'])
  })

  it('orders by sequence whatever order the chunks arrive in', () => {
    const shuffled = [...TRANSCRIPT].reverse()

    expect(streamBlocks(shuffled).map((block) => block.seq)).toEqual([1, 2, 3, 4, 5])
  })

  it('draws one block per kind, with its label and its body', () => {
    stubFetch(streamPage(TRANSCRIPT, false))

    draw()

    return waitFor(() => {
      const drawn = blocks()
      expect(drawn.map((block) => block.dataset['kind'])).toEqual([
        'system',
        'assistant',
        'tool',
        'tool',
        'assistant',
      ])
      // The thought is the dimmed, collapsible one (10 §Plugin renderers).
      expect(drawn[1]).toHaveClass('opacity-60')
      expect(drawn[0]).not.toHaveClass('opacity-60')
      expect(drawn[2]).toHaveTextContent('read · artificer/tui.py')
    })
  })

  it('folds a thought away and back', async () => {
    stubFetch(streamPage(TRANSCRIPT, false))
    const user = userEvent.setup()

    draw()

    const toggle = await screen.findByTestId('stream-thought-toggle')
    // Open by default: the reasoning is part of what happened.
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText(/the pane cycle is an index/i)).toBeInTheDocument()

    await user.click(toggle)

    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByText(/the pane cycle is an index/i)).not.toBeInTheDocument()
  })
})

/* -------------------------------------------------------------------- */
/* The focused attempt                                                   */
/* -------------------------------------------------------------------- */

describe('the focused attempt', () => {
  it('is the run’s most recent in-flight one', () => {
    expect(focusedTask(streamRun().tasks)?.id).toBe(STREAM_TASK)
  })

  it('falls back to the last attempt an agent measured', () => {
    const finished = streamRun().tasks?.map((task) =>
      task.status === 'in_progress' ? { ...task, status: 'done' as const } : task,
    )

    // Nothing is in flight, so the pane shows the transcript the run
    // ended on rather than nothing at all.
    expect(focusedTask(finished)?.id).toBe(STREAM_TASK)
  })

  it('has none in a run no agent has entered', () => {
    const queued = streamRun().tasks?.map((task) => ({
      ...task,
      status: 'ready' as const,
      stats: null,
    }))

    expect(focusedTask(queued)).toBeUndefined()
  })

  it('takes the drawer’s override when it names an attempt of the run', () => {
    expect(focusedTask(streamRun().tasks, 404)?.id).toBe(404)
  })

  it('ignores a ?task= left over from another run', () => {
    // Following it would draw a transcript this pane is not scoped to.
    expect(focusedTask(streamRun().tasks, 9001)?.id).toBe(STREAM_TASK)
  })

  it('fetches the attempt it focused, and says which it is', async () => {
    const urls = stubFetch(streamPage())

    draw()

    await waitFor(() => {
      expect(screen.getByTestId('stream-task')).toHaveTextContent(
        `task ${String(STREAM_TASK)} · engineering · streaming`,
      )
    })
    expect(urls).toEqual([
      expect.stringContaining(`/api/tasks/${String(STREAM_TASK)}/stream`),
    ])
  })

  it('follows the drawer’s override instead', async () => {
    const urls = stubFetch(streamPage(TRANSCRIPT, false))

    draw({ taskId: 404 })

    await waitFor(() => {
      expect(screen.getByTestId('stream-task')).toHaveTextContent(
        'task 404 · engineering · finished',
      )
    })
    expect(urls).toEqual([expect.stringContaining('/api/tasks/404/stream')])
  })

  it('draws the adapter line only once a stats entry named a model', async () => {
    stubFetch(streamPage())

    draw()

    expect(await screen.findByTestId('stream-adapter')).toHaveTextContent(
      'engineering → claude-opus-5',
    )
  })

  it('omits the adapter line when nothing reported a model', async () => {
    const unmeasured = streamRun({
      tasks: (streamRun().tasks ?? []).map((task) => ({ ...task, stats: null })),
    })
    stubFetch(streamPage())

    draw({ detail: unmeasured })

    await screen.findByTestId('stream-task')
    expect(screen.queryByTestId('stream-adapter')).not.toBeInTheDocument()
  })

  it('waits for a run rather than asking for a 404', () => {
    const urls = stubFetch(streamPage())

    draw({ runId: undefined, detail: null })

    expect(screen.getByRole('status')).toHaveTextContent('select a run')
    expect(urls).toEqual([])
  })

  it('says so when no agent has run, and asks for no transcript', () => {
    const urls = stubFetch(streamPage())
    const queued = streamRun({
      tasks: (streamRun().tasks ?? []).map((task) => ({
        ...task,
        status: 'ready' as const,
        stats: null,
      })),
    })

    draw({ detail: queued })

    expect(screen.getByRole('status')).toHaveTextContent('no agent has run')
    expect(urls).toEqual([])
  })
})

/* -------------------------------------------------------------------- */
/* Paging to the end of the transcript                                   */
/* -------------------------------------------------------------------- */

describe('a transcript longer than one page', () => {
  /** `DEFAULT_CHUNK_LIMIT` of `athanore/api/routers/tasks.py` (08). */
  const PAGE = 500

  /** A transcript of `count` `text` chunks, numbered as the store does. */
  function longTranscript(count: number): StreamChunk[] {
    return Array.from({ length: count }, (_, index) => ({
      seq: index + 1,
      kind: 'text' as const,
      text: `line ${String(index + 1)}\n`,
      created: '2026-09-08T09:00:00Z',
    }))
  }

  /**
   * `GET /api/tasks/{id}/stream` as the endpoint answers it: the chunks
   * after the cursor, at most one page of them, and `last_seq` as the
   * highest sequence **stored** rather than the highest in the page.
   */
  function server(whole: readonly StreamChunk[], live = false) {
    return (url: string) => {
      const after = Number(new URL(url).searchParams.get('after') ?? '0')
      return {
        chunks: whole.filter((chunk) => chunk.seq > after).slice(0, PAGE),
        last_seq: whole.reduce((highest, chunk) => Math.max(highest, chunk.seq), 0),
        live,
      }
    }
  }

  it('asks again after what it holds until it holds last_seq', async () => {
    const whole = longTranscript(620)
    const urls = stubFetch(server(whole))

    draw()

    // The end of the transcript is on screen — the fragments coalesce
    // into one block, so the last line is drawn and not merely cached.
    await waitFor(() => {
      expect(blocks()[0]).toHaveTextContent('line 620')
    })

    // Two requests: the first page, then everything after what it held.
    expect(urls).toHaveLength(2)
    expect(urls[0]).not.toContain('after=')
    expect(urls[1]).toContain(`after=${String(PAGE)}`)

    // And all of it is in the one cache entry the appender merges into.
    expect(queryClient.getQueryData(queryKeys.stream(STREAM_TASK))).toMatchObject({
      last_seq: 620,
      live: false,
    })
    const held = queryClient.getQueryData<StreamOut>(queryKeys.stream(STREAM_TASK))
    expect(held?.chunks).toHaveLength(620)
  })

  it('pages a live attempt too, and still calls it streaming', async () => {
    const urls = stubFetch(server(longTranscript(1100), true))

    draw()

    await waitFor(() => {
      expect(blocks()[0]).toHaveTextContent('line 1100')
    })
    expect(urls).toHaveLength(3)
    expect(screen.getByTestId('stream-task')).toHaveTextContent('· streaming')
    expect(screen.getByTestId('stream-caret')).toBeInTheDocument()
  })

  it('asks once when the first page is already the whole transcript', async () => {
    const urls = stubFetch(server(longTranscript(PAGE)))

    draw()

    await screen.findByTestId('stream-block')
    expect(urls).toHaveLength(1)
  })

  it('stops when a page brings nothing new, rather than asking forever', async () => {
    // `last_seq` names a chunk the page will not carry: a transcript
    // deleted between the two requests (07 §Retention). What was read is
    // drawn, and the pane stops asking.
    const trimmed = longTranscript(3)
    const urls = stubFetch((url: string) => ({
      ...server(trimmed)(url),
      last_seq: 9,
    }))

    draw()

    await waitFor(() => {
      expect(blocks()[0]).toHaveTextContent('line 3')
    })
    expect(urls).toHaveLength(2)
  })
})

/* -------------------------------------------------------------------- */
/* Before the transcript has arrived                                     */
/* -------------------------------------------------------------------- */

describe('the pane before its transcript', () => {
  it('says the transcript is loading rather than that there is none', async () => {
    // A request in flight: nobody has answered "did this attempt write
    // anything", so the pane may not say it wrote nothing.
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise<Response>(() => undefined)),
    )

    draw()

    expect(await screen.findByText('loading the transcript…')).toBeInTheDocument()
    expect(screen.queryByText(/wrote no transcript/)).not.toBeInTheDocument()
    // Neither streaming nor finished, for the same reason.
    expect(screen.getByTestId('stream-task')).toHaveTextContent(
      `task ${String(STREAM_TASK)} · engineering`,
    )
    expect(screen.getByTestId('stream-task')).not.toHaveTextContent('streaming')
  })

  it('names a request that failed rather than claiming an empty transcript', async () => {
    stubFetch({ detail: 'no' }, 500)

    draw()

    const card = await screen.findByTestId('pane-error')
    expect(card).toHaveTextContent(`/api/tasks/${String(STREAM_TASK)}/stream`)
    expect(screen.queryByText(/wrote no transcript/)).not.toBeInTheDocument()
  })

  it('says the attempt wrote nothing once an empty page has said so', async () => {
    stubFetch(streamPage([], false))

    draw()

    expect(
      await screen.findByText('this attempt wrote no transcript'),
    ).toBeInTheDocument()
  })

  it('says the agent has not spoken yet while an empty attempt is live', async () => {
    stubFetch(streamPage([], true))

    draw()

    expect(
      await screen.findByText('the agent has not said anything yet'),
    ).toBeInTheDocument()
  })
})

/* -------------------------------------------------------------------- */
/* The caret                                                             */
/* -------------------------------------------------------------------- */

describe('the caret', () => {
  it('blinks while the attempt is live', async () => {
    stubFetch(streamPage(TRANSCRIPT, true))

    draw()

    const caret = await screen.findByTestId('stream-caret')
    expect(caret.querySelector('.animate-ath-caret')).not.toBeNull()
  })

  it('is gone once the attempt has finished', async () => {
    stubFetch(streamPage(TRANSCRIPT, false))

    draw()

    await screen.findByTestId('stream-task')
    expect(screen.queryByTestId('stream-caret')).not.toBeInTheDocument()
  })
})

/* -------------------------------------------------------------------- */
/* Appending                                                             */
/* -------------------------------------------------------------------- */

describe('a task.stream event', () => {
  /** The chunk the event announces, as the server would send it back. */
  const NEXT: StreamChunk = {
    seq: 7,
    kind: 'text',
    text: ' Every pane now drives the same reducer.',
    created: '2026-09-08T09:00:07Z',
  }

  it('fetches after= what the pane holds, and refetches nothing', async () => {
    const urls = stubFetch(streamPage())

    draw()
    await screen.findByTestId('stream-task')
    expect(urls).toHaveLength(1)

    // The event carries the sequences that arrived (18); the pane has
    // the six before them, so the append asks for everything after 6.
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')
    const appended = stubFetch(streamPage([NEXT], true))

    await new Invalidator(queryClient).appendStream(STREAM_TASK, 7)

    // One request, for the one chunk — not the transcript again.
    expect(appended).toHaveLength(1)
    expect(appended[0]).toContain('after=6')
    expect(invalidate).not.toHaveBeenCalled()

    // And the pane drew it, without asking for anything else.
    await waitFor(() => {
      expect(blocks().at(-1)).toHaveTextContent(
        'Every pane now drives the same reducer.',
      )
    })
    expect(appended).toHaveLength(1)
  })

  it('reaches the pane’s own cache entry', async () => {
    stubFetch(streamPage())

    draw()
    await screen.findByTestId('stream-task')

    // The pane asks with a path and no `after`, which is what makes its
    // key the one the invalidation table names.
    expect(queryClient.getQueryData(queryKeys.stream(STREAM_TASK))).toMatchObject({
      last_seq: 6,
      live: true,
    })
  })
})

/**
 * The requests pane: the order the cards come in, what an answered card
 * says, and what a permission card shows about the call it is about
 * (`docs/v1/10-frontend.md` §Panes item 4, `docs/v1/06-requests.md`
 * §Surfaces).
 *
 * Three things this suite is deliberately strict about:
 *
 * - **the order is not the route's.** `GET /api/runs/{id}/requests`
 *   answers oldest first and says so is not a presentation
 *   (`athanore/store/repos/requests.py`); the pane puts pending first.
 *   The fixture's two pending requests are therefore *last* in what the
 *   server sends, so a pane that drew the list as it arrived fails here.
 * - **an answered card names its author.** A permission the clock
 *   answered is authored by `engine` (06 §Timeouts), and that is the one
 *   an operator reading back through a run most needs to spot.
 * - **the tool-call summary is bounded by this pane too.** `tool_call`
 *   is an open JSON object on the wire, so the bound
 *   `athanore/agents/policies.py` applies when it writes one is not the
 *   bound that protects the pane from what it reads.
 *
 * The controls themselves are `components/RequestPanel.tsx` and have
 * their own suite; what is asserted here is that the pane puts them in
 * the slot a pending card has and in no other, and that the pane's
 * `global` twin is the inbox rather than this list of nothing.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createAppQueryClient } from '../../api/client'
import { getRequestsApiRunsRunIdRequestsGetQueryKey } from '../../api/gen/@tanstack/react-query.gen'
import type { RequestView } from '../../api/gen/types.gen'
import {
  Requests,
  TOOL_CALL_CHARS,
  answerText,
  orderRequests,
  pendingCount,
  requestState,
  toolCallSummary,
} from '../kinds'
import { REQUESTS_RUN, REQUEST_LIST, STALE_REQUEST, request } from './fixtures'

let queryClient: QueryClient

/** Answer every request with `body`, and record the URLs asked for. */
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

/** The pane over a seeded list, so nothing is fetched while it draws. */
function draw(
  rows: readonly RequestView[] | null = REQUEST_LIST,
  options: { runId?: string | undefined } = {},
) {
  // `'runId' in options` and not a default parameter: passing
  // `undefined` explicitly is the case with no run selected, and a
  // default would swallow it.
  const runId = 'runId' in options ? options.runId : REQUESTS_RUN
  if (rows !== null && runId !== undefined) {
    queryClient.setQueryData(
      getRequestsApiRunsRunIdRequestsGetQueryKey({ path: { run_id: runId } }),
      rows,
    )
  }
  return render(
    <QueryClientProvider client={queryClient}>
      <Requests runId={runId} />
    </QueryClientProvider>,
  )
}

/** The cards in the order they are drawn. */
function cards() {
  return screen.getAllByTestId('request-card')
}

/** The ids of the cards in the order they are drawn. */
function cardIds() {
  return cards().map((row) => row.getAttribute('data-request'))
}

/** The card for one request, by the id it carries. */
function card(id: number): HTMLElement {
  const found = cards().find((row) => row.getAttribute('data-request') === String(id))
  if (found === undefined) throw new Error(`no card for request ${String(id)}`)
  return found
}

beforeEach(() => {
  queryClient = createAppQueryClient()
  // What is seeded is kept: nothing here refetches the list.
  queryClient.setDefaultOptions({ queries: { retry: false, staleTime: Infinity } })
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

/* -------------------------------------------------------------------- */
/* The order                                                             */
/* -------------------------------------------------------------------- */

describe('the order of the cards', () => {
  it('draws the pending requests first, then the rest as they were asked', () => {
    // The fixture is the route's own order: the two pending ones are
    // third and fourth.
    expect(REQUEST_LIST.map((row) => row.id)).toEqual([11, 12, 13, 14])

    draw()

    expect(cardIds()).toEqual(['13', '14', '11', '12'])
  })

  it('orders a stale request with the history and not with the pending', () => {
    // Stale is unanswered *and* unanswerable (08 §Requests): it belongs
    // below the questions a person can still act on, not above them.
    draw([STALE_REQUEST, ...REQUEST_LIST])

    expect(cardIds()).toEqual(['13', '14', '15', '11', '12'])
    expect(cards()[2]).toHaveAttribute('data-state', 'stale')
  })

  it('is a partition and not a sort, so each group keeps its order', () => {
    const ordered = orderRequests(REQUEST_LIST)

    expect(ordered.map((row) => row.id)).toEqual([13, 14, 11, 12])
    expect(pendingCount(REQUEST_LIST)).toBe(2)
    expect(requestState(REQUEST_LIST[0]!)).toBe('answered')
    expect(requestState(REQUEST_LIST[2]!)).toBe('pending')
    expect(requestState(STALE_REQUEST)).toBe('stale')
  })

  it('counts what was asked and what is still open in its header', () => {
    draw()

    expect(screen.getByTestId('request-count')).toHaveTextContent('4 asked')
    expect(screen.getByTestId('request-open')).toHaveTextContent('2 open')
  })

  it('says none are open when every request has been dealt with', () => {
    draw(REQUEST_LIST.slice(0, 2))

    expect(screen.getByTestId('request-open')).toHaveTextContent('none open')
  })
})

/* -------------------------------------------------------------------- */
/* One card                                                              */
/* -------------------------------------------------------------------- */

describe('one card', () => {
  it('labels a node request `node → operator` and an agent one `agent →`', () => {
    draw()

    const question = card(11)
    expect(within(question).getByTestId('request-from')).toHaveTextContent(
      'node → operator',
    )
    const permission = card(13)
    expect(within(permission).getByTestId('request-from')).toHaveTextContent(
      'agent → operator',
    )
  })

  it('carries the node, the kind, the timestamp and the prompt', () => {
    draw()

    const permission = card(13)
    expect(permission).toHaveTextContent('engineering')
    expect(within(permission).getByTestId('request-kind')).toHaveTextContent(
      'permission',
    )
    expect(within(permission).getByTestId('request-prompt')).toHaveTextContent(
      'permission: run the gate',
    )
    // The wall-clock time of the row, as the event log's first column is.
    expect(within(permission).getByTestId('request-time').textContent).toMatch(
      /^\d\d:\d\d:\d\d$/,
    )
  })

  it('marks the pending ones and no others', () => {
    draw([STALE_REQUEST, ...REQUEST_LIST])

    const states = cards().map((card) => card.getAttribute('data-state'))
    expect(states).toEqual(['pending', 'pending', 'stale', 'answered', 'answered'])
  })
})

/* -------------------------------------------------------------------- */
/* The answer                                                            */
/* -------------------------------------------------------------------- */

describe('an answered card', () => {
  it('shows the author and the text that was given', () => {
    draw()

    const question = card(11)
    expect(within(question).getByTestId('request-author')).toHaveTextContent('user')
    expect(within(question).getByTestId('request-value')).toHaveTextContent(
      'pnpm, as 02 §Library choices fixes it',
    )
    // The slot is the other branch of the same choice: an answered
    // request has no controls waiting to be built.
    expect(within(question).queryByTestId('request-controls')).not.toBeInTheDocument()
  })

  it('names `engine` as the author when the timeout answered it', () => {
    draw()

    // 06 §Timeouts: `permission_timeout_action` records an
    // engine-authored answer, which is exactly what an operator reading
    // back through a run wants told apart from their own.
    expect(within(card(12)).getByTestId('request-author')).toHaveTextContent('engine')
  })

  it('prints an options answer under the label the operator read', () => {
    draw()

    // The stored answer is `reject_once`; what was on the button was
    // `Reject`, and the card shows both.
    const value = within(card(12)).getByTestId('request-value')
    expect(value).toHaveTextContent('Reject')
    expect(value).toHaveTextContent('reject_once')
  })

  it('falls back to the id when the request no longer offers that option', () => {
    const answered = request({
      id: 21,
      mode: 'options',
      options: [{ option_id: 'yes', name: 'Yes' }],
      answer: 'no',
      answered_by: 'user',
    })

    expect(answerText(answered)).toBe('no')
  })

  it('prints a form answer as indented JSON, and a null answer as `—`', () => {
    const form = request({
      id: 22,
      mode: 'form',
      answer: { branch: 'feat/T063d' },
      answered_by: 'user',
    })
    expect(answerText(form)).toBe('{\n  "branch": "feat/T063d"\n}')

    // 08 §Requests: `answer` is null both before an answer and for an
    // answer that was null, and `answered_by` is what tells them apart.
    const empty = request({ id: 23, mode: 'form', answer: null, answered_by: 'user' })
    expect(answerText(empty)).toBe('—')
  })
})

/* -------------------------------------------------------------------- */
/* The controls slot                                                     */
/* -------------------------------------------------------------------- */

describe('the controls slot', () => {
  it('gives a pending card the answer controls, drawn by their mode', () => {
    draw()

    const slot = within(card(13)).getByTestId('request-controls')
    const panel = within(slot).getByTestId('request-panel')
    expect(panel).toHaveAttribute('data-mode', 'options')
    expect(panel).toHaveAccessibleName('awaiting one of')

    // The options are buttons now, in the order and under the labels the
    // agent offered (05 §Policies).
    const options = within(panel).getAllByRole('button')
    expect(options.map((option) => option.textContent)).toEqual([
      'Allow once',
      'Allow for this session',
      'Reject',
    ])
    expect(options[2]).toHaveAttribute('data-kind', 'reject_once')
  })

  it('draws a form request as a form and a text one as an input', () => {
    draw()

    expect(
      within(card(14)).getByTestId('request-panel'),
    ).toHaveAttribute('data-mode', 'form')
    expect(within(card(14)).getByTestId('action-form')).toBeInTheDocument()

    draw([request({ id: 24, mode: 'text', pending: true })])
    expect(screen.getAllByTestId('request-text').at(-1)).toBeInTheDocument()
  })

  it('gives an answered card no controls, because it has been answered', () => {
    draw()

    expect(within(card(11)).queryByTestId('request-controls')).not.toBeInTheDocument()
  })

  it('gives a stale request no slot, because it can no longer be answered', () => {
    draw([STALE_REQUEST])

    expect(screen.getByTestId('request-stale')).toHaveTextContent(
      'the attempt that asked has ended',
    )
    expect(screen.queryByTestId('request-controls')).not.toBeInTheDocument()
  })
})

/* -------------------------------------------------------------------- */
/* The tool call                                                         */
/* -------------------------------------------------------------------- */

describe('a permission card', () => {
  it('renders the bounded tool-call summary the policy stored', () => {
    draw()

    const summary = within(card(13)).getByTestId('request-tool-call')
    expect(within(summary).getByTestId('request-tool-heading')).toHaveTextContent(
      'execute · ./scripts/test.sh',
    )
    expect(within(summary).getByTestId('request-tool-input')).toHaveTextContent(
      '"command": "./scripts/test.sh"',
    )
  })

  it('keeps a long summary bounded, and says that it cut it', () => {
    const long = request({
      id: 25,
      source: 'agent',
      kind: 'permission',
      mode: 'options',
      prompt: 'permission: write the world',
      options: [{ option_id: 'allow_once', name: 'Allow once', kind: 'allow_once' }],
      // `tool_call` is an open JSON object on the wire, so this is a row
      // this pane may be handed however carefully the producer bounds
      // what it writes.
      tool_call: { title: 'write', kind: 'edit', raw_input: 'x'.repeat(4000) },
      pending: true,
    })

    draw([long])

    const input = screen.getByTestId('request-tool-input')
    expect(input.textContent).toHaveLength(TOOL_CALL_CHARS + 1)
    expect(input.textContent?.endsWith('…')).toBe(true)
    expect(screen.getByTestId('request-tool-call')).toHaveTextContent(
      `bounded at ${String(TOOL_CALL_CHARS)} characters`,
    )
  })

  it('draws no summary block for a permission whose summary says nothing', () => {
    draw([
      request({
        id: 26,
        source: 'agent',
        kind: 'permission',
        mode: 'options',
        options: [{ option_id: 'allow_once', name: 'Allow once' }],
        tool_call: {},
        pending: true,
      }),
    ])

    expect(screen.queryByTestId('request-tool-call')).not.toBeInTheDocument()
  })

  it('folds a field it does not know about into the input rather than dropping it', () => {
    // A summary written by a build that recorded more than this one
    // knows about is still shown — bounded, which is the property that
    // matters more than the shape.
    const summary = toolCallSummary({ title: 't', locations: ['/etc/passwd'] })

    expect(summary?.title).toBe('t')
    expect(summary?.input).toContain('/etc/passwd')
    expect(summary?.truncated).toBe(false)
    expect(toolCallSummary('not an object')).toBeNull()
    expect(toolCallSummary(null)).toBeNull()
  })
})

/* -------------------------------------------------------------------- */
/* The states the pane has nothing to draw in                            */
/* -------------------------------------------------------------------- */

describe('the pane with nothing to draw', () => {
  it('draws the inbox instead of a run’s list when nothing is selected', async () => {
    // The same tag is the `global` inbox twin (06 §SPA): the element is
    // one and the scope is what tells the two lists apart, so with no
    // run the pane asks `/api/requests` rather than a run's history.
    const urls = stubFetch([])

    draw(null, { runId: undefined })

    expect(await screen.findByTestId('pane-inbox')).toBeInTheDocument()
    expect(screen.queryByTestId('pane-requests')).not.toBeInTheDocument()
    expect(urls).toEqual([expect.stringContaining('/api/requests')])
  })

  it('says the list is loading before it claims the run asked nothing', async () => {
    stubFetch(REQUEST_LIST)

    draw(null)

    // The two are different facts, and only one of them is known yet.
    expect(screen.getByRole('status')).toHaveTextContent('loading the requests…')
    expect(await screen.findAllByTestId('request-card')).toHaveLength(
      REQUEST_LIST.length,
    )
  })

  it('says so when the run has asked nothing', () => {
    draw([])

    expect(screen.getByRole('status')).toHaveTextContent('this run has asked you nothing')
    expect(screen.getByTestId('request-count')).toHaveTextContent('0 asked')
  })

  it('names its own request when it fails', async () => {
    stubFetch({ error: 'no such run', code: 'not_found' }, 404)

    draw(null)

    const card = await screen.findByTestId('pane-error')
    expect(card).toHaveTextContent('no such run')
    expect(card).toHaveTextContent(`/api/runs/${REQUESTS_RUN}/requests`)
  })
})

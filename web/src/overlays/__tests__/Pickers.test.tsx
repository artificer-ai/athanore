/**
 * `Pickers`: the four palette-style lists and the one `POST` each of
 * them ends in (`overlays/Pickers.tsx`).
 *
 * The suite asserts on **what went out on the wire**, because that is
 * the whole of what a picker does and because the four look identical
 * on screen: a panel that retried when it was asked to cancel would pass
 * every test that only read the rows.
 *
 * The toast is mocked rather than rendered, as `NewRun`'s suite mocks
 * it: 10 §Components fixes that a landed action reports on the toast
 * surface, not how that surface looks.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createAppQueryClient } from '../../api/client'
import type {
  GraphNode,
  GraphOut,
  RunDetail,
  TaskStatus,
  TaskView,
} from '../../api/gen/types.gen'
import type { Overlay } from '../../routes/search'
import { Pickers } from '../Pickers'
import { PICKERS, type PickerKind } from '../pickers'

const { toast } = vi.hoisted(() => ({ toast: vi.fn() }))
vi.mock('sonner', () => ({ toast, Toaster: () => null }))

const RUN_ID = 'aaaa1111bbbb'

/** One attempt of `node`, as `GET /api/runs/{id}` sends it. */
function task(id: number, node: string, status: TaskStatus, attempt = 1): TaskView {
  return {
    id,
    run_id: RUN_ID,
    node,
    attempt,
    status,
    priority: 0,
    explicit: false,
    terminal: false,
    created: '2026-09-08T08:00:00Z',
  }
}

/** One node of the run's graph, as `GET /api/runs/{id}/graph` sends it. */
function graphNode(name: string, over: Partial<GraphNode> = {}): GraphNode {
  return {
    name,
    generation: 0,
    join: false,
    live: false,
    attempts: 0,
    state: 'idle',
    ...over,
  }
}

/**
 * A run with one attempt that failed, one still running, and one done —
 * so every picker has something to offer and something to hide.
 */
const TASKS: TaskView[] = [
  task(1, 'prepare', 'done'),
  task(2, 'implement', 'failed'),
  task(3, 'gate', 'in_progress'),
]

const RUN: RunDetail = {
  id: RUN_ID,
  workflow: 'feature_build',
  title: 'rebuild run detail',
  description: 'the detail pane, from the top',
  status: 'running',
  position: 1,
  created: '2026-09-08T08:00:00Z',
  updated: '2026-09-08T08:30:00Z',
  tasks: TASKS,
}

/** ...whose workflow fans out into a join, which `move` must not offer. */
const GRAPH: GraphOut = {
  nodes: [
    graphNode('prepare', { state: 'done', attempts: 1 }),
    graphNode('implement', { state: 'failed', attempts: 1 }),
    graphNode('gather', { join: true }),
    graphNode('merge'),
  ],
  edges: [],
}

/** What the fake server answers to one request. */
type Reply = { status: number; body: unknown }

/** What went out on the wire. */
type Sent = { url: string; method: string; body: unknown }

/** Every request the panel made, in order. */
let sent: Sent[]

/**
 * A server holding the run and its graph, answering every operation.
 *
 * `action` overrides the answer to whichever of the four `POST`s the
 * test drives, which is how a refusal is exercised.
 */
function stubServer(
  over: { run?: Reply; graph?: Reply; action?: Reply } = {},
): Sent[] {
  sent = []

  vi.stubGlobal(
    'fetch',
    vi.fn(async (request: Request) => {
      const body = request.body === null ? undefined : await request.clone().json()
      sent.push({ url: request.url, method: request.method, body })

      const reply =
        request.method === 'POST'
          ? (over.action ?? { status: 200, body: { task_id: 9 } })
          : request.url.includes('/graph')
            ? (over.graph ?? { status: 200, body: GRAPH })
            : (over.run ?? { status: 200, body: RUN })

      return new Response(JSON.stringify(reply.body), {
        status: reply.status,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )

  return sent
}

/** The POSTs of `sent`: the reads that filled the lists are not the subject. */
function posts(): Sent[] {
  return sent.filter((request) => request.method === 'POST')
}

let queryClient: QueryClient

/** The overlay over the button that opens it, which `esc` restores to. */
function Harness({
  overlay,
  runId,
  onClose,
}: {
  overlay: Overlay
  runId: string | undefined
  onClose: () => void
}) {
  const [open, setOpen] = useState(false)

  return (
    <QueryClientProvider client={queryClient}>
      <button type="button" onClick={() => setOpen(true)}>
        open picker
      </button>
      <Pickers
        overlay={open ? overlay : undefined}
        runId={runId}
        onClose={() => {
          setOpen(false)
          onClose()
        }}
      />
    </QueryClientProvider>
  )
}

/**
 * Draw the shell and open the picker.
 *
 * The opener is clicked here rather than in each test because a modal
 * dialog marks the rest of the document `aria-hidden`, so once the
 * overlay is up it cannot be found by role at all.
 */
async function open(kind: PickerKind, runId: string | null = RUN_ID) {
  const user = userEvent.setup()
  const onClose = vi.fn()
  render(<Harness overlay={kind} runId={runId ?? undefined} onClose={onClose} />)
  await user.click(screen.getByRole('button', { name: 'open picker' }))
  return { user, onClose }
}

/** The panel, once whichever notice or list it draws has settled. */
function panel() {
  return screen.getByTestId('picker')
}

/** One row of the attempt list. */
async function attempt(id: number) {
  return await waitFor(() => {
    const row = panel().querySelector(`[data-task="${String(id)}"]`)
    if (row === null) throw new Error(`no attempt row for #${String(id)}`)
    return row
  })
}

/** One row of the node list. */
async function node(name: string) {
  return await waitFor(() => {
    const row = panel().querySelector(`[data-node="${name}"]`)
    if (row === null) throw new Error(`no node row for ${name}`)
    return row
  })
}

/** Every node row on screen. */
function nodeNames(): string[] {
  return [...panel().querySelectorAll('[data-node]')].map(
    (row) => row.getAttribute('data-node') ?? '',
  )
}

beforeEach(() => {
  queryClient = createAppQueryClient()
  queryClient.setDefaultOptions({
    queries: { retry: false, staleTime: Infinity },
    mutations: { retry: false },
  })
  stubServer()
})

afterEach(() => {
  vi.unstubAllGlobals()
  toast.mockReset()
})

describe('Pickers', () => {
  it('is the palette’s panel, named after the command that opened it', async () => {
    await open('pick-retry')

    const dialog = await screen.findByRole('dialog', { name: 'retry task' })
    expect(within(dialog).getByText('esc close')).toBeInTheDocument()
    expect(within(dialog).getByTestId('picker-gloss')).toHaveTextContent(
      PICKERS['pick-retry'].task?.gloss ?? '',
    )
    expect(
      await screen.findByPlaceholderText('pick an attempt to retry'),
    ).toBeInTheDocument()
  })

  it('draws an attempt as node, attempt and status', async () => {
    await open('pick-move')

    const row = await attempt(2)
    expect(row).toHaveTextContent('implement')
    expect(row).toHaveTextContent('attempt 1 · #2')
    expect(row).toHaveTextContent('failed')
  })

  it('posts the retry of the attempt that was picked', async () => {
    const { user, onClose } = await open('pick-retry')

    await user.click(await attempt(2))

    await waitFor(() => {
      expect(posts()).toHaveLength(1)
    })
    expect(posts()[0]?.url).toContain('/api/tasks/2/retry')
    expect(posts()[0]?.method).toBe('POST')
    await waitFor(() => {
      expect(onClose).toHaveBeenCalled()
    })
    expect(toast).toHaveBeenCalledWith('retrying implement · task 9')
  })

  it('offers retry only the attempts that have stopped', async () => {
    await open('pick-retry')

    // `done` and `failed` are offered; the `in_progress` one is not,
    // because `Ops.retry` refuses it.
    expect(await attempt(1)).toBeInTheDocument()
    expect(await attempt(2)).toBeInTheDocument()
    expect(panel().querySelector('[data-task="3"]')).toBeNull()
  })

  it('posts the cancel of the attempt that is still going', async () => {
    const { user, onClose } = await open('pick-cancel')

    // ...and offers only that one: the two that finished keep the status
    // they earned.
    await waitFor(() => {
      expect(panel().querySelectorAll('[data-task]')).toHaveLength(1)
    })
    await user.click(await attempt(3))

    await waitFor(() => {
      expect(posts()).toHaveLength(1)
    })
    expect(posts()[0]?.url).toContain('/api/tasks/3/status')
    expect(posts()[0]?.body).toEqual({ status: 'cancelled' })
    await waitFor(() => {
      expect(onClose).toHaveBeenCalled()
    })
  })

  it('posts the rerun of the node that was picked, against the run', async () => {
    const { user, onClose } = await open('pick-rerun')

    await user.click(await node('gather'))

    await waitFor(() => {
      expect(posts()).toHaveLength(1)
    })
    expect(posts()[0]?.url).toContain(`/api/runs/${RUN_ID}/rerun`)
    expect(posts()[0]?.body).toEqual({ node: 'gather' })
    await waitFor(() => {
      expect(onClose).toHaveBeenCalled()
    })
    expect(toast).toHaveBeenCalledWith('rerunning gather · task 9')
  })

  it('offers rerun every node, joins included: a join replays arrivals', async () => {
    await open('pick-rerun')

    await node('prepare')
    expect(nodeNames()).toEqual(['prepare', 'implement', 'gather', 'merge'])
  })

  it('takes an attempt and then a node for a move, and posts once', async () => {
    const { user, onClose } = await open('pick-move')

    await user.click(await attempt(2))

    // Nothing has gone out: the attempt is a step, not an action.
    expect(posts()).toHaveLength(0)
    expect(screen.getByTestId('picker-gloss')).toHaveTextContent(
      'moving implement · attempt 1 · #2',
    )

    await user.click(await node('merge'))

    await waitFor(() => {
      expect(posts()).toHaveLength(1)
    })
    expect(posts()[0]?.url).toContain('/api/tasks/2/move')
    expect(posts()[0]?.body).toEqual({ node: 'merge' })
    await waitFor(() => {
      expect(onClose).toHaveBeenCalled()
    })
    expect(toast).toHaveBeenCalledWith('moved to merge · task 9')
  })

  it('hides join nodes from the move target list (04 §Fan-in, 409)', async () => {
    const { user } = await open('pick-move')

    await user.click(await attempt(2))
    await node('prepare')

    expect(nodeNames()).toEqual(['prepare', 'implement', 'merge'])
    expect(panel().querySelector('[data-node="gather"]')).toBeNull()
  })

  it('says so rather than showing an empty box, when nothing is eligible', async () => {
    stubServer({
      run: { status: 200, body: { ...RUN, tasks: [task(3, 'gate', 'in_progress')] } },
    })
    await open('pick-retry')

    const notice = await screen.findByTestId('picker-notice')
    expect(notice).toHaveTextContent(PICKERS['pick-retry'].task?.empty ?? '')
    // No input over an empty list.
    expect(screen.queryByPlaceholderText('pick an attempt to retry')).toBeNull()
  })

  it('says so when every node of the workflow is a join', async () => {
    stubServer({
      graph: {
        status: 200,
        body: { nodes: [graphNode('gather', { join: true })], edges: [] },
      },
    })
    const { user } = await open('pick-move')

    await user.click(await attempt(2))

    expect(await screen.findByTestId('picker-notice')).toHaveTextContent(
      PICKERS['pick-move'].node?.empty ?? '',
    )
  })

  it('keeps the panel up on a refusal, with what the server said', async () => {
    stubServer({
      action: {
        status: 409,
        body: { error: "node 'gather' is a join; a task cannot be moved into one" },
      },
    })
    const { user, onClose } = await open('pick-rerun')

    await user.click(await node('gather'))

    expect(await screen.findByTestId('picker-error')).toHaveTextContent(
      "node 'gather' is a join; a task cannot be moved into one",
    )
    expect(onClose).not.toHaveBeenCalled()
    // ...and the rows are still there to pick another one from.
    expect(await node('merge')).toBeInTheDocument()
  })

  it('takes one action at a time: a second row over the first is refused', async () => {
    // A server that records the POST and never answers it, which is the
    // only way to ask what a second pick does while the first is out.
    sent = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (request: Request) => {
        const body = request.body === null ? undefined : await request.clone().json()
        sent.push({ url: request.url, method: request.method, body })
        if (request.method === 'POST') return new Promise<Response>(() => {})
        return new Response(
          JSON.stringify(request.url.includes('/graph') ? GRAPH : RUN),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        )
      }),
    )

    const { user } = await open('pick-rerun')

    await user.click(await node('gather'))
    await user.click(await node('merge'))

    expect(posts()).toHaveLength(1)
    expect(posts()[0]?.body).toEqual({ node: 'gather' })
  })

  it('says which run to select when none is', async () => {
    await open('pick-retry', null)

    expect(await screen.findByTestId('picker-notice')).toHaveTextContent(
      'select a run to pick one of its attempts',
    )
    expect(sent).toHaveLength(0)
  })

  it('draws a refused read as the refusal, not as an empty graph', async () => {
    stubServer({
      graph: { status: 404, body: { error: 'no workflow named feature_build' } },
    })
    await open('pick-rerun')

    expect(await screen.findByTestId('picker-notice')).toHaveTextContent(
      'no workflow named feature_build',
    )
  })

  it('is closed by `esc`, and gives focus back to whatever opened it', async () => {
    const { user, onClose } = await open('pick-retry')
    await attempt(2)

    await user.keyboard('{Escape}')

    expect(onClose).toHaveBeenCalledOnce()
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'open picker' })).toHaveFocus()
    })
    expect(posts()).toHaveLength(0)
  })
})

/**
 * `TaskDrawer`: everything about one attempt, and the three operator
 * operations that act on it (`overlays/TaskDrawer.tsx`).
 *
 * The suite asserts on **what went out on the wire** wherever it can, as
 * the pickers' does: three buttons that look the same and post to three
 * endpoints are three different operations, and a drawer that cancelled
 * when it was asked to retry would pass every test that only read the
 * panel.
 *
 * The toast is mocked rather than rendered, as `Pickers`' suite mocks
 * it: 10 §Components fixes that a landed action reports on the toast
 * surface, not how that surface looks.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createAppQueryClient } from '../../api/client'
import type { GraphNode, GraphOut, TaskDetail } from '../../api/gen/types.gen'
import { RETRY_BLOCKED, TaskDrawer } from '../TaskDrawer'

const { toast } = vi.hoisted(() => ({ toast: vi.fn() }))
vi.mock('sonner', () => ({ toast, Toaster: () => null }))

const RUN_ID = 'aaaa1111bbbb'
const TASK_ID = 41

/**
 * The attempt the suite is about: the second run of `implement`, failed,
 * inside a fan-out, retried by hand out of the first.
 */
const FAILED: TaskDetail = {
  id: TASK_ID,
  run_id: RUN_ID,
  node: 'implement',
  attempt: 2,
  status: 'failed',
  priority: 6,
  explicit: true,
  terminal: false,
  created: '2026-09-08T08:00:00Z',
  started: '2026-09-08T08:01:00Z',
  finished: '2026-09-08T08:09:00Z',
  payload: { title: 'rebuild run detail' },
  result: null,
  error: 'AssertionError: the gate is red',
  lineage: { reason: 'manual_retry', from: 40 },
  branch: [{ fanout: 26, index: 1, count: 3, key: 'beta' }],
  stats: { model: 'sonnet', tokens_in: 612 },
  submissions: [
    { id: 7, task_id: TASK_ID, payload: { verdict: 'reject' }, created: '2026-09-08T08:08:00Z' },
  ],
}

/** One node of the run's graph, as `GET /api/runs/{id}/graph` sends it. */
function graphNode(name: string, over: Partial<GraphNode> = {}): GraphNode {
  return { name, generation: 0, join: false, live: false, attempts: 0, state: 'idle', ...over }
}

/** ...whose workflow fans out into a join, which `move` must not offer. */
const GRAPH: GraphOut = {
  nodes: [
    graphNode('prepare', { state: 'done', attempts: 1 }),
    graphNode('implement', { state: 'failed', attempts: 2 }),
    graphNode('gather', { join: true }),
    graphNode('merge'),
  ],
  edges: [],
}

/** What the fake server answers to one request. */
type Reply = { status: number; body: unknown }

/** What went out on the wire. */
type Sent = { url: string; method: string; body: unknown }

let sent: Sent[]

/** A server holding the attempt and its run's graph. */
function stubServer(
  over: { task?: Reply; graph?: Reply; action?: Reply } = {},
): Sent[] {
  sent = []

  vi.stubGlobal(
    'fetch',
    vi.fn(async (request: Request) => {
      const body = request.body === null ? undefined : await request.clone().json()
      sent.push({ url: request.url, method: request.method, body })

      const reply =
        request.method === 'POST'
          ? (over.action ?? { status: 200, body: { task_id: 99, ok: true } })
          : request.url.includes('/graph')
            ? (over.graph ?? { status: 200, body: GRAPH })
            : (over.task ?? { status: 200, body: FAILED })

      return new Response(JSON.stringify(reply.body), {
        status: reply.status,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )

  return sent
}

/** The POSTs of `sent`: the reads that filled the panel are not the subject. */
function posts(): Sent[] {
  return sent.filter((request) => request.method === 'POST')
}

let queryClient: QueryClient

/** The overlay over the button that opens it, which `esc` restores to. */
function Harness({
  taskId,
  onClose,
  onOpenTask,
  onFocusStream,
}: {
  taskId: number | undefined
  onClose: () => void
  onOpenTask?: (taskId: number) => void
  onFocusStream?: (taskId: number) => void
}) {
  const [open, setOpen] = useState(false)

  return (
    <QueryClientProvider client={queryClient}>
      <button type="button" onClick={() => setOpen(true)}>
        open drawer
      </button>
      <TaskDrawer
        open={open}
        taskId={taskId}
        onClose={() => {
          setOpen(false)
          onClose()
        }}
        onOpenTask={onOpenTask}
        onFocusStream={onFocusStream}
      />
    </QueryClientProvider>
  )
}

/**
 * Draw the shell, open the drawer, and wait for the attempt.
 *
 * The opener is clicked here rather than in each test because a modal
 * dialog marks the rest of the document `aria-hidden`, so once the panel
 * is up it cannot be found by role at all.
 */
async function open(
  // `null`, not `undefined`: a default parameter is taken for
  // `undefined`, so "no attempt selected" needs a value of its own.
  taskId: number | null = TASK_ID,
  handlers: {
    onOpenTask?: (taskId: number) => void
    onFocusStream?: (taskId: number) => void
  } = {},
) {
  const user = userEvent.setup()
  const onClose = vi.fn()
  render(<Harness taskId={taskId ?? undefined} onClose={onClose} {...handlers} />)
  await user.click(screen.getByRole('button', { name: 'open drawer' }))
  return { user, onClose }
}

/** The panel itself. */
function panel() {
  return screen.getByTestId('task-drawer')
}

/** One control of the panel, once the attempt has arrived. */
async function control(testId: string) {
  return await waitFor(() => screen.getByTestId(testId))
}

beforeEach(() => {
  queryClient = createAppQueryClient()
  queryClient.setDefaultOptions({
    queries: { retry: false, staleTime: Infinity },
    mutations: { retry: false },
  })
  toast.mockClear()
  stubServer()
})

describe('TaskDrawer', () => {
  it('renders a failed attempt whole: its lineage, branch, error and the rest', async () => {
    await open()

    await waitFor(() => {
      expect(screen.getByTestId('task-lineage')).toHaveTextContent(
        'an operator’s retry of task #40',
      )
    })

    // The header names the attempt and colours its status.
    expect(screen.getByRole('dialog', { name: /task #41/ })).toBeInTheDocument()
    expect(screen.getByTestId('task-status')).toHaveTextContent('failed')

    // Every section 10 §Overlays names.
    expect(screen.getByTestId('task-branch')).toHaveTextContent(
      'branch 2 of 3 · beta · from task #26',
    )
    expect(screen.getByTestId('task-error')).toHaveTextContent(
      'AssertionError: the gate is red',
    )
    expect(screen.getByTestId('task-payload')).toHaveTextContent('rebuild run detail')
    expect(screen.getByTestId('task-result')).toHaveTextContent('null')
    expect(screen.getByTestId('task-submissions')).toHaveTextContent('reject')
    expect(screen.getByTestId('task-stats')).toHaveTextContent('sonnet')

    // …and the meta grid, including where the priority came from.
    expect(screen.getByTestId('task-meta')).toHaveTextContent('6 · declared on the node')
    expect(screen.getByTestId('task-meta')).toHaveTextContent(RUN_ID)
  })

  it('opens the attempt its lineage came out of', async () => {
    const onOpenTask = vi.fn()
    await open(TASK_ID, { onOpenTask })

    const link = await waitFor(() => screen.getByTestId('task-link'))
    await userEvent.click(link)

    expect(onOpenTask).toHaveBeenCalledExactlyOnceWith(40)
  })

  it('lists a join’s arrivals as attempts to open', async () => {
    stubServer({
      task: {
        status: 200,
        body: {
          ...FAILED,
          status: 'done',
          lineage: { reason: 'join', from: 26, arrivals: [31, 32] },
        },
      },
    })
    const onOpenTask = vi.fn()
    await open(TASK_ID, { onOpenTask })

    await waitFor(() => {
      expect(screen.getByTestId('task-lineage')).toHaveTextContent(
        'the join closing the fan-out at task #26',
      )
    })
    const links = panel().querySelectorAll('[data-task]')
    expect([...links].map((link) => link.getAttribute('data-task'))).toEqual([
      '26',
      '31',
      '32',
    ])
  })

  it('retries the attempt, and says so on the toast surface', async () => {
    const { user, onClose } = await open()

    await user.click(await control('task-retry'))

    await waitFor(() => {
      expect(posts()).toHaveLength(1)
    })
    expect(posts()[0]?.url).toContain('/api/tasks/41/retry')
    expect(posts()[0]?.body).toBeUndefined()
    expect(toast).toHaveBeenCalledWith('retrying implement · task 99')
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('refuses to retry an attempt that has not stopped', async () => {
    stubServer({ task: { status: 200, body: { ...FAILED, status: 'in_progress' } } })
    const { user } = await open()

    const retry = await control('task-retry')
    expect(retry).toBeDisabled()
    expect(retry).toHaveAttribute('title', RETRY_BLOCKED)

    await user.click(retry)
    expect(posts()).toHaveLength(0)
  })

  it('sets a status, and never offers the one the attempt is in', async () => {
    const { user } = await open()

    await waitFor(() => {
      expect(screen.getAllByTestId('task-status-set')).toHaveLength(3)
    })
    const targets = screen
      .getAllByTestId('task-status-set')
      .map((button) => button.getAttribute('data-status'))
    expect(targets).toEqual(['ready', 'cancelled', 'dead_letter'])

    await user.click(screen.getByText('dead letter'))

    await waitFor(() => {
      expect(posts()).toHaveLength(1)
    })
    expect(posts()[0]?.url).toContain('/api/tasks/41/status')
    expect(posts()[0]?.body).toEqual({ status: 'dead_letter' })
  })

  it('drops the current status from the targets', async () => {
    stubServer({ task: { status: 200, body: { ...FAILED, status: 'cancelled' } } })
    await open()

    await waitFor(() => {
      expect(screen.getAllByTestId('task-status-set')).toHaveLength(2)
    })
    expect(
      screen.getAllByTestId('task-status-set').map((b) => b.getAttribute('data-status')),
    ).toEqual(['ready', 'dead_letter'])
  })

  it('moves the attempt, and never offers a join as the target', async () => {
    const { user } = await open()

    await user.click(await control('task-move'))

    await waitFor(() => {
      expect(screen.getAllByTestId('task-move-node').length).toBeGreaterThan(0)
    })
    const nodes = screen
      .getAllByTestId('task-move-node')
      .map((button) => button.getAttribute('data-node'))
    // 04 §Fan-in refuses a move into a join with a 409, so `gather` is
    // not offered at all.
    expect(nodes).toEqual(['prepare', 'implement', 'merge'])
    // …and the node the attempt is already on is not a move.
    expect(
      screen
        .getAllByTestId('task-move-node')
        .find((button) => button.getAttribute('data-node') === 'implement'),
    ).toBeDisabled()

    await user.click(screen.getByRole('button', { name: 'merge' }))

    await waitFor(() => {
      expect(posts()).toHaveLength(1)
    })
    expect(posts()[0]?.url).toContain('/api/tasks/41/move')
    expect(posts()[0]?.body).toEqual({ node: 'merge' })
  })

  it('asks for the graph only once a move is being considered', async () => {
    const { user } = await open()

    await waitFor(() => {
      expect(screen.getByTestId('task-payload')).toBeInTheDocument()
    })
    expect(sent.some((request) => request.url.includes('/graph'))).toBe(false)

    await user.click(await control('task-move'))

    await waitFor(() => {
      expect(sent.some((request) => request.url.includes('/graph'))).toBe(true)
    })
  })

  it('keeps the drawer up on a refusal, and draws what it said', async () => {
    stubServer({
      action: { status: 409, body: { error: 'the task is in progress', code: 'conflict' } },
    })
    const { user, onClose } = await open()

    await user.click(await control('task-retry'))

    expect(await screen.findByTestId('task-drawer-error')).toHaveTextContent(
      'the task is in progress',
    )
    expect(onClose).not.toHaveBeenCalled()
  })

  it('hands the attempt to the agent pane on focus stream', async () => {
    const onFocusStream = vi.fn()
    const { user } = await open(TASK_ID, { onFocusStream })

    await user.click(await control('task-focus-stream'))

    expect(onFocusStream).toHaveBeenCalledExactlyOnceWith(TASK_ID)
    // The navigation closes the drawer; the drawer does not close itself
    // and then navigate, which would be two writes of one search.
    expect(posts()).toHaveLength(0)
  })

  it('says which attempt it cannot read, rather than drawing an empty panel', async () => {
    stubServer({ task: { status: 404, body: { error: 'no such task', code: 'not_found' } } })
    await open()

    expect(await screen.findByTestId('task-drawer-notice')).toHaveTextContent(
      'no such task',
    )
  })

  it('asks for nothing with no attempt selected', async () => {
    await open(null)

    expect(await screen.findByTestId('task-drawer-notice')).toHaveTextContent(
      'no attempt is selected',
    )
    expect(sent).toHaveLength(0)
  })

  it('closes on esc, back where focus came from', async () => {
    const { user, onClose } = await open()

    await waitFor(() => {
      expect(screen.getByTestId('task-payload')).toBeInTheDocument()
    })
    await user.keyboard('{Escape}')

    expect(onClose).toHaveBeenCalledOnce()
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'open drawer' })).toHaveFocus()
    })
  })

  it('draws no section for what an attempt has not got', async () => {
    stubServer({
      task: {
        status: 200,
        body: {
          id: 5,
          run_id: RUN_ID,
          node: 'prepare',
          attempt: 1,
          status: 'ready',
          priority: 0,
          explicit: false,
          terminal: false,
          created: '2026-09-08T08:00:00Z',
        },
      },
    })
    await open(5)

    await waitFor(() => {
      expect(screen.getByTestId('task-payload')).toBeInTheDocument()
    })
    const sections = [...panel().querySelectorAll('[data-section]')].map((section) =>
      section.getAttribute('data-section'),
    )
    // Real data only: no ERROR, no BRANCH, no SUBMISSIONS, no STATS for
    // an attempt nobody has claimed yet.
    expect(sections).toEqual(['LINEAGE', 'PAYLOAD', 'RESULT'])
    // …and no STARTED or FINISHED row in the grid.
    expect(within(screen.getByTestId('task-meta')).queryByText('STARTED')).toBeNull()
  })
})

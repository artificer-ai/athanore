/**
 * `NewRun`: the mock's panel, and the submission behind its one primary
 * button (`overlays/NewRun.tsx`, `docs/v1/10-frontend.md` §Overlays,
 * D34, D57).
 *
 * The suite asserts on **what went out on the wire** wherever it can.
 * `top` and `bottom` draw identically once the chip is pressed, and the
 * only difference between them is the second POST that follows the first
 * (D57) — so an overlay that had forgotten it would pass every test that
 * only looked at the screen.
 *
 * The toast is mocked rather than rendered, as `RequestPanel`'s suite
 * mocks it: what 10 §Components fixes is that something the operator
 * cannot correct goes to the toast surface, not how that surface looks.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createAppQueryClient } from '../../api/client'
import type { WorkflowOut } from '../../api/gen/types.gen'
import { ALL_WORKFLOWS, useUi } from '../../store/ui'
import { NewRun, NEW_RUN_TITLE } from '../NewRun'

const { toast } = vi.hoisted(() => ({ toast: vi.fn() }))
vi.mock('sonner', () => ({ toast, Toaster: () => null }))

/** One registered workflow, as `GET /api/workflows` sends it. */
function workflow(name: string, start: string): WorkflowOut {
  return {
    name,
    start,
    capacity: 1,
    in_flight: 0,
    nodes: {},
    plugin: { panels: [], actions: [] },
    pool: 'default',
  }
}

const WORKFLOWS = [
  workflow('feature_build', 'prepare'),
  workflow('gamedev', 'design'),
]

/** What the fake server answers to one request. */
type Reply = { status: number; body: unknown }

/** What went out on the wire. */
type Sent = { url: string; method: string; body: unknown }

const CREATED: Reply = { status: 201, body: { run_id: '01JRUN' } }
const MOVED: Reply = { status: 200, body: { position: 1 } }

/**
 * A server that answers each route once, with the reply given for it.
 *
 * `submit` and `position` default to the happy answers, because most of
 * these tests are about which of the two was asked for at all.
 */
function stubServer(
  over: { workflows?: Reply; submit?: Reply; position?: Reply } = {},
): Sent[] {
  const sent: Sent[] = []

  vi.stubGlobal(
    'fetch',
    vi.fn(async (request: Request) => {
      const body = request.body === null ? undefined : await request.clone().json()
      sent.push({ url: request.url, method: request.method, body })

      const reply = request.url.includes('/position')
        ? (over.position ?? MOVED)
        : request.url.includes('/runs')
          ? (over.submit ?? CREATED)
          : (over.workflows ?? { status: 200, body: WORKFLOWS })

      return new Response(JSON.stringify(reply.body), {
        status: reply.status,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )

  return sent
}

/**
 * A server that records the request and never answers it.
 *
 * The workflows are already cached by the time a test wants this, so the
 * only request it ever takes is the submission — held open, which is the
 * only way to ask what a second press does while the first is still out.
 */
function hangingServer(): Sent[] {
  const sent: Sent[] = []

  vi.stubGlobal(
    'fetch',
    vi.fn(async (request: Request) => {
      const body = request.body === null ? undefined : await request.clone().json()
      sent.push({ url: request.url, method: request.method, body })
      return new Promise<Response>(() => {})
    }),
  )

  return sent
}

/** The POSTs of `sent`: the GET of the workflows is not the subject. */
function posts(sent: Sent[]): Sent[] {
  return sent.filter((request) => request.method === 'POST')
}

let queryClient: QueryClient

/** The overlay over the button that opens it, which `esc` restores to. */
function Harness({ onClose }: { onClose: () => void }) {
  const [open, setOpen] = useState(false)

  return (
    <QueryClientProvider client={queryClient}>
      <button type="button" onClick={() => setOpen(true)}>
        new run
      </button>
      <NewRun
        open={open}
        onClose={() => {
          setOpen(false)
          onClose()
        }}
      />
    </QueryClientProvider>
  )
}

/**
 * Draw the shell. The opener is read here rather than in each test
 * because a modal dialog marks the rest of the document `aria-hidden`,
 * so once the overlay is up it cannot be found by role at all.
 */
function draw() {
  const user = userEvent.setup()
  const onClose = vi.fn()
  render(<Harness onClose={onClose} />)
  return { user, onClose, opener: screen.getByRole('button', { name: 'new run' }) }
}

/** ...and open it, waiting for the form the workflows unlock. */
async function open() {
  const shell = draw()
  await shell.user.click(shell.opener)
  await screen.findByTestId('new-run-form')
  return shell
}

beforeEach(() => {
  queryClient = createAppQueryClient()
  queryClient.setDefaultOptions({
    queries: { retry: false, staleTime: Infinity },
    mutations: { retry: false },
  })
  useUi.setState({ runFilter: { workflow: ALL_WORKFLOWS, query: '' } })
  stubServer()
})

afterEach(() => {
  vi.unstubAllGlobals()
  toast.mockReset()
})

describe('NewRun', () => {
  it('is the mock’s panel, field for field', async () => {
    await open()

    const panel = screen.getByRole('dialog', { name: NEW_RUN_TITLE })
    expect(within(panel).getByText('⌘⏎ submit · esc cancel')).toBeInTheDocument()

    // A chip per registered workflow, the first of them chosen, so the
    // form is submittable the moment it is drawn.
    const chips = within(
      within(panel).getByRole('radiogroup', { name: 'WORKFLOW' }),
    ).getAllByRole('radio')
    expect(chips.map((chip) => chip.textContent)).toEqual([
      'feature_build',
      'gamedev',
    ])
    expect(chips[0]).toHaveAttribute('data-state', 'on')

    expect(within(panel).getByLabelText('TITLE')).toHaveAttribute(
      'placeholder',
      'short summary',
    )
    expect(within(panel).getByLabelText('DESCRIPTION')).toHaveAttribute(
      'placeholder',
      'what should the agents do',
    )

    // POSITION is the mock's 1–10 priority slider, replaced (D34).
    const positions = within(
      within(panel).getByRole('radiogroup', { name: 'POSITION' }),
    ).getAllByRole('radio')
    expect(positions.map((chip) => chip.textContent)).toEqual(['top', 'bottom'])
    expect(positions[1]).toHaveAttribute('data-state', 'on')

    expect(within(panel).getByRole('button', { name: 'cancel' })).toBeInTheDocument()
    expect(within(panel).getByRole('button', { name: 'submit run' })).toBeInTheDocument()
  })

  it('puts the caret in TITLE, which is the first thing to type', async () => {
    await open()

    await waitFor(() => {
      expect(screen.getByLabelText('TITLE')).toHaveFocus()
    })
  })

  it('reads ENTRY NODE from the chosen workflow’s graph', async () => {
    const { user } = await open()

    expect(screen.getByTestId('new-run-entry-node')).toHaveTextContent('prepare')

    await user.click(screen.getByRole('radio', { name: 'gamedev' }))

    expect(screen.getByTestId('new-run-entry-node')).toHaveTextContent('design')
  })

  it('posts the run and nothing else for `bottom`', async () => {
    const { user, onClose } = await open()
    const sent = stubServer()

    await user.type(screen.getByLabelText('TITLE'), 'port the settings module')
    await user.type(screen.getByLabelText('DESCRIPTION'), 'see 11 §Settings')
    await user.click(screen.getByRole('button', { name: 'submit run' }))

    await waitFor(() => {
      expect(onClose).toHaveBeenCalledTimes(1)
    })

    const wire = posts(sent)
    expect(wire).toHaveLength(1)
    expect(wire[0]?.url).toContain('/api/workflows/feature_build/runs')
    expect(wire[0]?.body).toEqual({
      title: 'port the settings module',
      description: 'see 11 §Settings',
    })
  })

  it('posts the run and then the move to index 0 for `top` (D57)', async () => {
    const { user, onClose } = await open()
    const sent = stubServer()

    await user.click(screen.getByRole('radio', { name: 'gamedev' }))
    await user.click(screen.getByRole('radio', { name: 'top' }))
    await user.type(screen.getByLabelText('TITLE'), 'the boss fight')
    await user.click(screen.getByRole('button', { name: 'submit run' }))

    await waitFor(() => {
      expect(onClose).toHaveBeenCalledTimes(1)
    })

    const wire = posts(sent)
    expect(wire).toHaveLength(2)
    expect(wire[0]?.url).toContain('/api/workflows/gamedev/runs')
    expect(wire[0]?.body).toEqual({ title: 'the boss fight', description: '' })
    expect(wire[1]?.url).toContain('/api/runs/01JRUN/position')
    expect(wire[1]?.body).toEqual({ index: 0 })
  })

  it('submits on ⌘⏎, from the description as well', async () => {
    const { user, onClose } = await open()
    const sent = stubServer()

    await user.type(screen.getByLabelText('TITLE'), 'a run')
    await user.click(screen.getByLabelText('DESCRIPTION'))
    await user.keyboard('a note{Meta>}{Enter}{/Meta}')

    await waitFor(() => {
      expect(onClose).toHaveBeenCalledTimes(1)
    })
    expect(posts(sent)[0]?.body).toEqual({ title: 'a run', description: 'a note' })
  })

  it('takes one submission at a time, ⌘⏎ included (D171 (1))', async () => {
    const { user, onClose } = await open()
    // A server that takes the POST and never answers, so the first
    // submission is still out when the second ⌘⏎ arrives — which is the
    // whole test: a run cannot be un-queued, and `submit run` going
    // `disabled` does nothing about a keystroke that never touches it.
    const sent = hangingServer()

    await user.type(screen.getByLabelText('TITLE'), 'a run')
    await user.keyboard('{Meta>}{Enter}{/Meta}')

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'submit run' })).toBeDisabled()
    })
    expect(posts(sent)).toHaveLength(1)

    // Once with the pending state on screen, and once more in the same
    // tick as the render that put it there.
    await user.keyboard('{Meta>}{Enter}{/Meta}')
    fireEvent.keyDown(screen.getByTestId('new-run-form'), {
      key: 'Enter',
      metaKey: true,
    })
    // Long enough for a submission that was going to happen to have
    // happened: validation resolves in a microtask and `mutate` calls
    // `fetch` in the next one.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0))
    })

    expect(posts(sent)).toHaveLength(1)
    expect(onClose).not.toHaveBeenCalled()
  })

  it('submits again after either refusal: the latch is not a one-shot', async () => {
    const { user, onClose } = await open()
    const refused = stubServer({
      submit: { status: 409, body: { error: 'unknown workflow' } },
    })

    // Refused by the form, so nothing went out...
    await user.click(screen.getByLabelText('TITLE'))
    await user.keyboard('{Meta>}{Enter}{/Meta}')
    await screen.findByTestId('new-run-title-error')
    expect(posts(refused)).toHaveLength(0)

    // ...refused by the server, which is the failure the form stands
    // up under (D171 (1))...
    await user.type(screen.getByLabelText('TITLE'), 'a run')
    await user.keyboard('{Meta>}{Enter}{/Meta}')
    await screen.findByTestId('new-run-error')
    expect(posts(refused)).toHaveLength(1)

    // ...and taken, once the operator has changed what was wrong.
    const sent = stubServer()
    await user.click(screen.getByRole('radio', { name: 'gamedev' }))
    await user.keyboard('{Meta>}{Enter}{/Meta}')

    await waitFor(() => {
      expect(onClose).toHaveBeenCalledTimes(1)
    })
    expect(posts(sent)).toHaveLength(1)
  })

  it('blocks an empty title without asking the server', async () => {
    const { user, onClose } = await open()
    const sent = stubServer()

    await user.type(screen.getByLabelText('TITLE'), '   ')
    await user.click(screen.getByRole('button', { name: 'submit run' }))

    expect(await screen.findByTestId('new-run-title-error')).toHaveTextContent(
      'a run needs a title',
    )
    expect(posts(sent)).toHaveLength(0)
    expect(onClose).not.toHaveBeenCalled()
  })

  it('clears the run list’s filter so the queued run is in it', async () => {
    useUi.setState({ runFilter: { workflow: 'gamedev', query: 'boss' } })
    const { user } = await open()

    await user.type(screen.getByLabelText('TITLE'), 'port the settings module')
    await user.click(screen.getByRole('button', { name: 'submit run' }))

    await waitFor(() => {
      expect(useUi.getState().runFilter).toEqual({
        workflow: ALL_WORKFLOWS,
        query: '',
      })
    })
  })

  it('leaves the form up under a refused submission', async () => {
    const { user, onClose } = await open()
    stubServer({ submit: { status: 409, body: { error: 'unknown workflow' } } })

    await user.type(screen.getByLabelText('TITLE'), 'port the settings module')
    await user.click(screen.getByRole('button', { name: 'submit run' }))

    expect(await screen.findByTestId('new-run-error')).toHaveTextContent(
      'unknown workflow',
    )
    expect(onClose).not.toHaveBeenCalled()
    expect(screen.getByLabelText('TITLE')).toHaveValue('port the settings module')
  })

  it('closes on a failed move and says the run is at the bottom', async () => {
    const { user, onClose } = await open()
    stubServer({ position: { status: 422, body: { error: 'index must be an integer' } } })

    await user.click(screen.getByRole('radio', { name: 'top' }))
    await user.type(screen.getByLabelText('TITLE'), 'port the settings module')
    await user.click(screen.getByRole('button', { name: 'submit run' }))

    // The run exists: pressing the button again would queue a second
    // one, so the overlay ends and the toast carries what happened.
    await waitFor(() => {
      expect(toast).toHaveBeenCalledWith('index must be an integer')
    })
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('closes on cancel and on esc', async () => {
    const { user, onClose, opener } = await open()

    await user.click(screen.getByRole('button', { name: 'cancel' }))
    expect(onClose).toHaveBeenCalledTimes(1)

    await user.click(opener)
    await screen.findByTestId('new-run-form')
    await user.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalledTimes(2)
  })

  it('gives focus back to whatever opened it', async () => {
    const { user, opener } = await open()

    await user.keyboard('{Escape}')

    await waitFor(() => {
      expect(opener).toHaveFocus()
    })
  })

  it('makes the same round trip on a second open, workflows cached', async () => {
    const { user, opener } = await open()
    await user.keyboard('{Escape}')
    await waitFor(() => {
      expect(opener).toHaveFocus()
    })

    // The workflows are in the cache now, so the form mounts in the same
    // commit as the panel — and Radix skips its own open-focus when
    // something inside the panel already has focus. An `autoFocus` on
    // TITLE would take it, the element to go back to would never be
    // recorded, and `esc` would land on `<body>`.
    await user.click(opener)
    await screen.findByTestId('new-run-form')
    await waitFor(() => {
      expect(screen.getByLabelText('TITLE')).toHaveFocus()
    })

    await user.keyboard('{Escape}')

    await waitFor(() => {
      expect(opener).toHaveFocus()
    })
  })

  it('offers nothing to submit when the server runs no workflows', async () => {
    stubServer({ workflows: { status: 200, body: [] } })
    const { user, opener } = draw()

    await user.click(opener)

    expect(await screen.findByText('no workflows are registered')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'submit run' })).toBeNull()
    expect(screen.getByRole('button', { name: 'cancel' })).toBeInTheDocument()
  })

  it('says so when the workflows could not be read', async () => {
    stubServer({ workflows: { status: 500, body: { error: 'no registry' } } })
    const { user, opener } = draw()

    await user.click(opener)

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'the workflows could not be read',
    )
  })
})

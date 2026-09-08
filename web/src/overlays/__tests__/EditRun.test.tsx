/**
 * `EditRun`: the two fields 10 §Overlays allows, and the one `PATCH`
 * behind `save` (`overlays/EditRun.tsx`, `docs/v1/08-api.md` §Runs,
 * `docs/v1/04-engine.md` §Operator operations).
 *
 * The suite asserts on **what went out on the wire** wherever it can. A
 * panel that sent only the field the operator touched would look
 * identical on screen and could never blank a description, because an
 * absent field means "leave it alone" to the server.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createAppQueryClient } from '../../api/client'
import type { RunDetail } from '../../api/gen/types.gen'
import { EditRun, EDIT_RUN_FALLBACK, EDIT_RUN_TITLE } from '../EditRun'

const RUN_ID = 'aaaa1111bbbb'

const RUN: RunDetail = {
  id: RUN_ID,
  workflow: 'feature_build',
  title: 'rebuild run detail',
  description: 'the detail pane, from the top',
  status: 'running',
  position: 1,
  created: '2026-09-08T08:00:00Z',
  updated: '2026-09-08T08:30:00Z',
  tasks: [],
}

/** What the fake server answers to one request. */
type Reply = { status: number; body: unknown }

/** What went out on the wire. */
type Sent = { url: string; method: string; body: unknown }

let sent: Sent[]

/** A server holding the run, answering the `PATCH` with `over.patch`. */
function stubServer(over: { run?: Reply; patch?: Reply } = {}): Sent[] {
  sent = []

  vi.stubGlobal(
    'fetch',
    vi.fn(async (request: Request) => {
      const body = request.body === null ? undefined : await request.clone().json()
      sent.push({ url: request.url, method: request.method, body })

      const reply =
        request.method === 'PATCH'
          ? (over.patch ?? { status: 200, body: RUN })
          : (over.run ?? { status: 200, body: RUN })

      return new Response(JSON.stringify(reply.body), {
        status: reply.status,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )

  return sent
}

/** The edits of `sent`: the read that filled the form is not the subject. */
function patches(): Sent[] {
  return sent.filter((request) => request.method === 'PATCH')
}

let queryClient: QueryClient

/** The overlay over the button that opens it, which `esc` restores to. */
function Harness({
  runId,
  onClose,
}: {
  runId: string | undefined
  onClose: () => void
}) {
  const [open, setOpen] = useState(false)

  return (
    <QueryClientProvider client={queryClient}>
      <button type="button" onClick={() => setOpen(true)}>
        edit run
      </button>
      <EditRun
        open={open}
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
 * Draw the shell and open the overlay, waiting for the form the run
 * unlocks.
 *
 * The opener is clicked here rather than in each test because a modal
 * dialog marks the rest of the document `aria-hidden`, so once the
 * overlay is up it cannot be found by role at all.
 */
async function open(runId: string | null = RUN_ID) {
  const user = userEvent.setup()
  const onClose = vi.fn()
  render(<Harness runId={runId ?? undefined} onClose={onClose} />)
  await user.click(screen.getByRole('button', { name: 'edit run' }))
  return { user, onClose }
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
})

describe('EditRun', () => {
  it('is the two fields 10 §Overlays allows, and no third', async () => {
    await open()
    await screen.findByTestId('edit-run-form')

    const panel = screen.getByRole('dialog', { name: EDIT_RUN_TITLE })
    expect(within(panel).getByText('⌘⏎ save · esc cancel')).toBeInTheDocument()
    expect(within(panel).getByLabelText('TITLE')).toBeInTheDocument()
    expect(within(panel).getByLabelText('DESCRIPTION')).toBeInTheDocument()
    // The mock's priority slider is the New Run overlay's POSITION and
    // `POST /api/runs/{id}/position` (D34, D57); it is not here.
    expect(within(panel).queryByText(/POSITION|PRIORITY/)).toBeNull()
    expect(within(panel).getByRole('button', { name: 'cancel' })).toBeInTheDocument()
    expect(within(panel).getByRole('button', { name: 'save' })).toBeInTheDocument()
  })

  it('opens on the run’s own title and description', async () => {
    await open()
    await screen.findByTestId('edit-run-form')

    expect(screen.getByLabelText('TITLE')).toHaveValue('rebuild run detail')
    expect(screen.getByLabelText('DESCRIPTION')).toHaveValue(
      'the detail pane, from the top',
    )
  })

  it('puts the caret in TITLE, which is the first thing to type', async () => {
    await open()
    await screen.findByTestId('edit-run-form')

    await waitFor(() => {
      expect(screen.getByLabelText('TITLE')).toHaveFocus()
    })
  })

  it('patches both fields, and closes', async () => {
    const { user, onClose } = await open()
    await screen.findByTestId('edit-run-form')

    await user.clear(screen.getByLabelText('TITLE'))
    await user.type(screen.getByLabelText('TITLE'), 'rebuild the detail pane')
    await user.click(screen.getByRole('button', { name: 'save' }))

    await waitFor(() => {
      expect(patches()).toHaveLength(1)
    })
    expect(patches()[0]?.url).toContain(`/api/runs/${RUN_ID}`)
    expect(patches()[0]?.body).toEqual({
      title: 'rebuild the detail pane',
      // Untouched, and still sent: an absent field means "leave it
      // alone" on the wire, so a panel that omitted it could never
      // blank one.
      description: 'the detail pane, from the top',
    })
    await waitFor(() => {
      expect(onClose).toHaveBeenCalled()
    })
  })

  it('sends an emptied description as the empty string it now is', async () => {
    const { user } = await open()
    await screen.findByTestId('edit-run-form')

    await user.clear(screen.getByLabelText('DESCRIPTION'))
    await user.click(screen.getByRole('button', { name: 'save' }))

    await waitFor(() => {
      expect(patches()).toHaveLength(1)
    })
    expect(patches()[0]?.body).toEqual({
      title: 'rebuild run detail',
      description: '',
    })
  })

  it('trims the title, as the server does', async () => {
    const { user } = await open()
    await screen.findByTestId('edit-run-form')

    await user.clear(screen.getByLabelText('TITLE'))
    await user.type(screen.getByLabelText('TITLE'), '  spaced out  ')
    await user.click(screen.getByRole('button', { name: 'save' }))

    await waitFor(() => {
      expect(patches()).toHaveLength(1)
    })
    expect(patches()[0]?.body).toMatchObject({ title: 'spaced out' })
  })

  it('refuses an empty title without asking the server (04 §Operator ops)', async () => {
    const { user, onClose } = await open()
    await screen.findByTestId('edit-run-form')

    await user.clear(screen.getByLabelText('TITLE'))
    await user.click(screen.getByRole('button', { name: 'save' }))

    expect(await screen.findByTestId('edit-run-title-error')).toHaveTextContent(
      'a run needs a title',
    )
    expect(patches()).toHaveLength(0)
    expect(onClose).not.toHaveBeenCalled()
  })

  it('keeps the panel up on a refusal, with what the server said', async () => {
    stubServer({
      patch: { status: 404, body: { error: 'run aaaa1111bbbb does not exist' } },
    })
    const { user, onClose } = await open()
    await screen.findByTestId('edit-run-form')

    await user.click(screen.getByRole('button', { name: 'save' }))

    expect(await screen.findByTestId('edit-run-error')).toHaveTextContent(
      'run aaaa1111bbbb does not exist',
    )
    expect(onClose).not.toHaveBeenCalled()
  })

  it('says something when the refusal said nothing', async () => {
    stubServer({ patch: { status: 500, body: {} } })
    const { user } = await open()
    await screen.findByTestId('edit-run-form')

    await user.click(screen.getByRole('button', { name: 'save' }))

    expect(await screen.findByTestId('edit-run-error')).toHaveTextContent(
      EDIT_RUN_FALLBACK,
    )
  })

  it('takes one save at a time', async () => {
    // A server that records the PATCH and never answers it, which is the
    // only way to ask what a second press does while the first is out.
    sent = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (request: Request) => {
        const body = request.body === null ? undefined : await request.clone().json()
        sent.push({ url: request.url, method: request.method, body })
        if (request.method === 'PATCH') return new Promise<Response>(() => {})
        return new Response(JSON.stringify(RUN), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }),
    )

    const { user } = await open()
    await screen.findByTestId('edit-run-form')

    // ⌘⏎ reaches the form whatever the button looks like, so it is the
    // second press worth asking about.
    await user.click(screen.getByRole('button', { name: 'save' }))
    await user.keyboard('{Meta>}{Enter}{/Meta}')

    expect(patches()).toHaveLength(1)
  })

  it('saves from ⌘⏎, including from the description box', async () => {
    const { user } = await open()
    await screen.findByTestId('edit-run-form')

    await user.click(screen.getByLabelText('DESCRIPTION'))
    await user.keyboard('{Meta>}{Enter}{/Meta}')

    await waitFor(() => {
      expect(patches()).toHaveLength(1)
    })
  })

  it('says which run to select when none is, and asks for nothing', async () => {
    await open(null)

    expect(await screen.findByTestId('edit-run-notice')).toHaveTextContent(
      'select a run to edit it',
    )
    expect(sent).toHaveLength(0)
    // ...and still closes, which is the one thing the panel can do.
    expect(screen.getByRole('button', { name: 'cancel' })).toBeInTheDocument()
  })

  it('draws a refused read as the refusal, not as an empty form', async () => {
    stubServer({ run: { status: 404, body: { error: 'no such run' } } })
    await open()

    expect(await screen.findByTestId('edit-run-notice')).toHaveTextContent(
      'no such run',
    )
    expect(screen.queryByTestId('edit-run-form')).toBeNull()
  })

  it('is closed by `esc`, and gives focus back to whatever opened it', async () => {
    const { user, onClose } = await open()
    await screen.findByTestId('edit-run-form')

    await user.keyboard('{Escape}')

    expect(onClose).toHaveBeenCalledOnce()
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'edit run' })).toHaveFocus()
    })
    expect(patches()).toHaveLength(0)
  })
})

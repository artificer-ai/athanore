/**
 * `DeleteRun`: the one confirm in the keyboard map
 * (`overlays/DeleteRun.tsx`).
 *
 * `delete(run)` is the only operator operation that destroys anything,
 * so the suite is mostly about what does *not* go out: an overlay that
 * deleted on `⏎`, or on `cancel`, would look identical on screen.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createAppQueryClient } from '../../api/client'
import type { RunDetail } from '../../api/gen/types.gen'
import { DeleteRun, DELETE_RUN_TITLE } from '../DeleteRun'

const RUN_ID = 'aaaa1111bbbb'

const RUN: RunDetail = {
  id: RUN_ID,
  workflow: 'feature_build',
  title: 'rebuild run detail',
  status: 'failed',
  position: 1,
  created: '2026-09-08T08:00:00Z',
  updated: '2026-09-08T08:30:00Z',
  tasks: [],
}

/** What the fake server answers to one request. */
type Reply = { status: number; body: unknown }

/** What went out on the wire. */
type Sent = { url: string; method: string }

let sent: Sent[]

function stubServer(over: { del?: Reply } = {}): Sent[] {
  sent = []

  vi.stubGlobal(
    'fetch',
    vi.fn(async (request: Request) => {
      sent.push({ url: request.url, method: request.method })

      const reply =
        request.method === 'DELETE'
          ? (over.del ?? { status: 204, body: null })
          : { status: 200, body: RUN }

      return new Response(reply.body === null ? null : JSON.stringify(reply.body), {
        status: reply.status,
        ...(reply.body === null
          ? {}
          : { headers: { 'Content-Type': 'application/json' } }),
      })
    }),
  )

  return sent
}

/** The deletions of `sent`: the read that named the run is not the subject. */
function deletions(): Sent[] {
  return sent.filter((request) => request.method === 'DELETE')
}

let queryClient: QueryClient

/** The overlay over the button that opens it, which `esc` restores to. */
function Harness({
  runId,
  onClose,
  onDeleted,
}: {
  runId: string | undefined
  onClose: () => void
  onDeleted?: () => void
}) {
  const [open, setOpen] = useState(false)

  return (
    <QueryClientProvider client={queryClient}>
      <button type="button" onClick={() => setOpen(true)}>
        open confirm
      </button>
      <DeleteRun
        open={open}
        runId={runId}
        onClose={() => {
          setOpen(false)
          onClose()
        }}
        onDeleted={onDeleted}
      />
    </QueryClientProvider>
  )
}

async function open(runId: string | null = RUN_ID) {
  const user = userEvent.setup()
  const onClose = vi.fn()
  const onDeleted = vi.fn()
  render(
    <Harness runId={runId ?? undefined} onClose={onClose} onDeleted={onDeleted} />,
  )
  await user.click(screen.getByRole('button', { name: 'open confirm' }))
  return { user, onClose, onDeleted }
}

beforeEach(() => {
  queryClient = createAppQueryClient()
  queryClient.setDefaultOptions({
    queries: { retry: false, staleTime: Infinity },
    mutations: { retry: false },
  })
  stubServer()
})

describe('DeleteRun', () => {
  it('names the run and what goes with it', async () => {
    await open()

    expect(screen.getByRole('dialog', { name: DELETE_RUN_TITLE })).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getByTestId('delete-run')).toHaveTextContent('rebuild run detail')
    })
    // 04: "cancel, then delete run and **all** child rows".
    expect(screen.getByTestId('delete-run')).toHaveTextContent('agent transcripts')
    expect(screen.getByTestId('delete-run')).toHaveTextContent('cannot be undone')
  })

  it('deletes the run and clears the selection', async () => {
    const { user, onClose, onDeleted } = await open()

    await user.click(screen.getByRole('button', { name: 'delete run' }))

    await waitFor(() => {
      expect(deletions()).toHaveLength(1)
    })
    expect(deletions()[0]?.url).toContain(`/api/runs/${RUN_ID}`)
    expect(onDeleted).toHaveBeenCalledOnce()
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('focuses cancel, so ⏎ on a dialog that appeared does not delete', async () => {
    const { user, onClose } = await open()

    expect(screen.getByRole('button', { name: 'cancel' })).toHaveFocus()

    await user.keyboard('{Enter}')

    expect(deletions()).toHaveLength(0)
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('deletes nothing on esc', async () => {
    const { user, onClose } = await open()

    await user.keyboard('{Escape}')

    expect(deletions()).toHaveLength(0)
    expect(onClose).toHaveBeenCalledOnce()
    expect(screen.getByRole('button', { name: 'open confirm' })).toHaveFocus()
  })

  it('keeps the panel up on a refusal, and draws what it said', async () => {
    stubServer({
      del: { status: 500, body: { error: 'the store is down', code: 'internal' } },
    })
    const { user, onClose } = await open()

    await user.click(screen.getByRole('button', { name: 'delete run' }))

    expect(await screen.findByTestId('delete-run-error')).toHaveTextContent(
      'the store is down',
    )
    expect(onClose).not.toHaveBeenCalled()
  })

  it('has nothing to delete with no run selected', async () => {
    await open(null)

    expect(screen.getByTestId('delete-run-notice')).toHaveTextContent(
      'select a run to delete it',
    )
    expect(screen.getByRole('button', { name: 'delete run' })).toBeDisabled()
    expect(sent).toHaveLength(0)
  })
})

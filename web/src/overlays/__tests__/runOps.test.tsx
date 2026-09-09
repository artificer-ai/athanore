/**
 * `overlays/runOps.ts`: the five run-level operator operations of
 * `docs/v1/04-engine.md` §Operator operations that are a key and a
 * palette row rather than a panel (`docs/v1/08-api.md` §Runs).
 *
 * `pauseDirection` is tested without a DOM because it is a rule of 04;
 * the calls are tested through a component, because they are `useMutation`
 * and the assertion worth making is which URL and which body went out.
 */
import { QueryClientProvider, type QueryClient } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createAppQueryClient } from '../../api/client'
import type { RunStatus } from '../../api/gen/types.gen'
import { pauseDirection, useRunOps } from '../runOps'

const { toast } = vi.hoisted(() => {
  const fn = Object.assign(vi.fn(), { error: vi.fn() })
  return { toast: fn }
})
vi.mock('sonner', () => ({ toast, Toaster: () => null }))

const RUN_ID = 'aaaa1111bbbb'

/** What went out on the wire. */
type Sent = { url: string; method: string; body: unknown }

let sent: Sent[]

function stubServer(reply: { status: number; body: unknown } = { status: 200, body: { ok: true } }) {
  sent = []

  vi.stubGlobal(
    'fetch',
    vi.fn(async (request: Request) => {
      const body = request.body === null ? undefined : await request.clone().json()
      sent.push({ url: request.url, method: request.method, body })

      return new Response(JSON.stringify(reply.body), {
        status: reply.status,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
}

let queryClient: QueryClient

/** A button per operation, over one run. */
function Harness({ status }: { status: RunStatus }) {
  return (
    <QueryClientProvider client={queryClient}>
      <Buttons status={status} />
    </QueryClientProvider>
  )
}

function Buttons({ status }: { status: RunStatus }) {
  const ops = useRunOps()

  return (
    <>
      <button type="button" onClick={() => ops.pauseResume(RUN_ID, status)}>
        p
      </button>
      <button type="button" onClick={() => ops.cancel(RUN_ID)}>
        c
      </button>
      <button type="button" onClick={() => ops.reorder(RUN_ID, 'up')}>
        up
      </button>
      <button type="button" onClick={() => ops.reorder(RUN_ID, 'down')}>
        down
      </button>
    </>
  )
}

beforeEach(() => {
  queryClient = createAppQueryClient()
  queryClient.setDefaultOptions({
    queries: { retry: false, staleTime: Infinity },
    mutations: { retry: false },
  })
  toast.mockClear()
  toast.error.mockClear()
  stubServer()
})

describe('pauseDirection', () => {
  it('pauses a running or queued run and resumes a paused one (04)', () => {
    expect(pauseDirection('running')).toBe('pause')
    expect(pauseDirection('queued')).toBe('pause')
    expect(pauseDirection('paused')).toBe('resume')
  })

  it('is neither for a terminal run, or for no run at all', () => {
    for (const status of ['completed', 'failed', 'cancelled'] as const) {
      expect(pauseDirection(status)).toBeNull()
    }
    expect(pauseDirection(undefined)).toBeNull()
  })
})

describe('useRunOps', () => {
  it('posts /pause for a running run and /resume for a paused one', async () => {
    const user = userEvent.setup()

    const running = render(<Harness status="running" />)
    await user.click(screen.getByRole('button', { name: 'p' }))
    await waitFor(() => {
      expect(sent).toHaveLength(1)
    })
    expect(sent[0]?.url).toContain(`/api/runs/${RUN_ID}/pause`)
    running.unmount()

    render(<Harness status="paused" />)
    await user.click(screen.getByRole('button', { name: 'p' }))
    await waitFor(() => {
      expect(sent).toHaveLength(2)
    })
    expect(sent[1]?.url).toContain(`/api/runs/${RUN_ID}/resume`)
  })

  it('posts nothing for a run that is neither', async () => {
    const user = userEvent.setup()
    render(<Harness status="completed" />)

    await user.click(screen.getByRole('button', { name: 'p' }))

    expect(sent).toHaveLength(0)
  })

  it('reports what cancel stopped, which is the note only it fills', async () => {
    stubServer({ status: 200, body: { ok: true, note: 'stopped 2 attempts' } })
    const user = userEvent.setup()
    render(<Harness status="running" />)

    await user.click(screen.getByRole('button', { name: 'c' }))

    await waitFor(() => {
      expect(sent).toHaveLength(1)
    })
    expect(sent[0]?.url).toContain(`/api/runs/${RUN_ID}/cancel`)
    expect(toast).toHaveBeenCalledWith('run cancelled · stopped 2 attempts')
  })

  it('reorders by direction, and reports the position the server settled on', async () => {
    stubServer({ status: 200, body: { position: 3 } })
    const user = userEvent.setup()
    render(<Harness status="queued" />)

    await user.click(screen.getByRole('button', { name: 'up' }))
    await waitFor(() => {
      expect(sent).toHaveLength(1)
    })
    expect(sent[0]?.url).toContain(`/api/runs/${RUN_ID}/position`)
    expect(sent[0]?.body).toEqual({ direction: -1 })
    expect(toast).toHaveBeenCalledWith('position 3')

    await user.click(screen.getByRole('button', { name: 'down' }))
    await waitFor(() => {
      expect(sent).toHaveLength(2)
    })
    expect(sent[1]?.body).toEqual({ direction: 1 })
  })

  it('reports a refusal rather than swallowing it', async () => {
    stubServer({ status: 409, body: { error: 'the run is not paused', code: 'conflict' } })
    const user = userEvent.setup()
    render(<Harness status="paused" />)

    await user.click(screen.getByRole('button', { name: 'p' }))

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith('the run is not paused')
    })
  })
})

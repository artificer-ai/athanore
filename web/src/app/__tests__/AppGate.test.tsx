import type { QueryClient } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createAppQueryClient } from '../../api/client'
import type { Me } from '../../api/gen/types.gen'
import { usePrefs } from '../../store/prefs'
import { useUi } from '../../store/ui'
import { AppGate } from '../AppGate'
import { Providers } from '../providers'

const LOOPBACK: Me = {
  auth: 'off',
  authenticated: true,
  features: [],
  started_at: '2026-09-08T09:00:00Z',
  version: '0.1.0',
}

/** Answer `GET /api/me` with `me`, and count how often it was asked. */
function serve(me: Me) {
  const fetchMock = vi.fn(
    async () =>
      new Response(JSON.stringify(me), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
  )
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function gate(queryClient: QueryClient = createAppQueryClient()) {
  return render(
    <Providers client={queryClient}>
      <AppGate>
        <div data-testid="shell">the shell</div>
      </AppGate>
    </Providers>,
  )
}

describe('AppGate', () => {
  beforeEach(() => {
    usePrefs.setState({ token: null })
    useUi.setState({ needsToken: false })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows the shell unprompted on a loopback server', async () => {
    serve(LOOPBACK)
    gate()

    expect(await screen.findByTestId('shell')).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('says so while it is still asking', () => {
    serve(LOOPBACK)
    gate()

    expect(screen.getByRole('status')).toHaveTextContent('connecting')
    expect(screen.queryByTestId('shell')).toBeNull()
  })

  it('asks for the token when the server wants one and this caller has none', async () => {
    serve({ ...LOOPBACK, auth: 'token', authenticated: false })
    gate()

    expect(await screen.findByRole('dialog', { name: 'token required' })).toBeInTheDocument()
    expect(screen.queryByTestId('shell')).toBeNull()
  })

  it('shows the shell when the server wants a token and this caller has it', async () => {
    serve({ ...LOOPBACK, auth: 'token', authenticated: true })
    gate()

    expect(await screen.findByTestId('shell')).toBeInTheDocument()
  })

  it('asks for the token after a 401, whatever /api/me last said', async () => {
    serve(LOOPBACK)
    gate()
    expect(await screen.findByTestId('shell')).toBeInTheDocument()

    useUi.getState().setNeedsToken(true)

    expect(await screen.findByRole('dialog', { name: 'token required' })).toBeInTheDocument()
  })

  it('asks the server again, from a clean slate', async () => {
    serve({ ...LOOPBACK, auth: 'token', authenticated: false })
    const queryClient = createAppQueryClient()
    gate(queryClient)
    await screen.findByRole('dialog', { name: 'token required' })

    const fetchMock = serve(LOOPBACK)
    await userEvent.click(screen.getByRole('button', { name: 'try again' }))

    expect(await screen.findByTestId('shell')).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalled()
    expect(useUi.getState().needsToken).toBe(false)
  })

  it('reports a server that is not there, and retries on the operator’s word', async () => {
    const down = vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    })
    vi.stubGlobal('fetch', down)
    const queryClient = createAppQueryClient()
    // The one retry of `createAppQueryClient` is asserted on in
    // `api/__tests__/client.test.ts`; waiting out its backoff here would
    // buy this test nothing but a second of wall clock.
    queryClient.setDefaultOptions({ queries: { retry: false } })
    gate(queryClient)

    expect(await screen.findByRole('dialog', { name: 'no server' })).toBeInTheDocument()
    expect(screen.queryByTestId('shell')).toBeNull()

    serve(LOOPBACK)
    await userEvent.click(screen.getByRole('button', { name: 'try again' }))

    await waitFor(() => expect(screen.getByTestId('shell')).toBeInTheDocument())
  })
})

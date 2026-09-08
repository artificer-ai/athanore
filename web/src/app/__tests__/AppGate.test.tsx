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

/**
 * Answer `GET /api/me` as a server that accepts exactly `good`, which is
 * what makes a token typed into the screen mean anything.
 */
function serveGuarded(good: string) {
  const fetchMock = vi.fn(async (request: Request) => {
    const authenticated = request.headers.get('Authorization') === `Bearer ${good}`
    return new Response(
      JSON.stringify({ ...LOOPBACK, auth: 'token', authenticated }),
      { status: 200, headers: { 'Content-Type': 'application/json' } },
    )
  })
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
    expect(screen.getByLabelText('operator token')).toBeInTheDocument()
    expect(screen.queryByTestId('shell')).toBeNull()
  })

  it('shows the shell when the server wants a token and this caller has it', async () => {
    serve({ ...LOOPBACK, auth: 'token', authenticated: true })
    usePrefs.setState({ token: 's3cret' })
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

  it('shows the shell once the operator produces a token the server accepts', async () => {
    const fetchMock = serveGuarded('s3cret')
    gate()
    await screen.findByRole('dialog', { name: 'token required' })

    await userEvent.type(screen.getByLabelText('operator token'), 's3cret')
    await userEvent.click(screen.getByRole('button', { name: 'save token' }))

    expect(await screen.findByTestId('shell')).toBeInTheDocument()
    expect(usePrefs.getState().token).toBe('s3cret')
    expect(useUi.getState().needsToken).toBe(false)
    expect(fetchMock.mock.calls.at(-1)?.[0].headers.get('Authorization')).toBe(
      'Bearer s3cret',
    )
  })

  it('returns to the token screen when the stored token is cleared', async () => {
    serveGuarded('s3cret')
    usePrefs.setState({ token: 's3cret' })
    gate()
    expect(await screen.findByTestId('shell')).toBeInTheDocument()

    usePrefs.getState().setToken(null)

    expect(await screen.findByRole('dialog', { name: 'token required' })).toBeInTheDocument()
    expect(screen.queryByTestId('shell')).toBeNull()
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

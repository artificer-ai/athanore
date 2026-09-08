import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createAppQueryClient, meQueryOptions } from '../../api/client'
import type { Me } from '../../api/gen/types.gen'
import { Providers } from '../../app/providers'
import { usePrefs } from '../../store/prefs'
import { useUi } from '../../store/ui'
import { TokenScreen } from '../TokenScreen'

const NETWORK: Me = {
  auth: 'token',
  authenticated: false,
  features: [],
  started_at: '2026-09-08T09:00:00Z',
  version: '0.1.0',
}

/**
 * Answer `GET /api/me` as a server that accepts exactly `good`, and
 * record every `Request` the client built.
 */
function serve(good: string) {
  const fetchMock = vi.fn(async (request: Request) => {
    const authenticated = request.headers.get('Authorization') === `Bearer ${good}`
    return new Response(JSON.stringify({ ...NETWORK, authenticated }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

/** The token screen, mounted on a query client that has asked already. */
function mount(me: Me = NETWORK) {
  const queryClient = createAppQueryClient()
  queryClient.setQueryData(meQueryOptions().queryKey, me)
  render(
    <Providers client={queryClient}>
      <TokenScreen />
    </Providers>,
  )
  return queryClient
}

describe('TokenScreen', () => {
  beforeEach(() => {
    usePrefs.setState({ token: null })
    useUi.setState({ needsToken: true })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('is an overlay panel with a field for the token', () => {
    serve('s3cret')
    mount()

    expect(screen.getByRole('dialog', { name: 'token required' })).toBeInTheDocument()
    expect(screen.getByLabelText('operator token')).toHaveAttribute('type', 'password')
    expect(screen.getByRole('button', { name: 'save token' })).toBeDisabled()
  })

  it('stores what is typed and sends it on the next request', async () => {
    const fetchMock = serve('s3cret')
    mount()

    await userEvent.type(screen.getByLabelText('operator token'), 's3cret')
    await userEvent.click(screen.getByRole('button', { name: 'save token' }))

    expect(usePrefs.getState().token).toBe('s3cret')
    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    const request = fetchMock.mock.calls.at(-1)?.[0]
    expect(request?.url).toContain('/api/me')
    expect(request?.headers.get('Authorization')).toBe('Bearer s3cret')
  })

  it('asks /api/me again, and drops what this tab holds without a credential', async () => {
    const fetchMock = serve('s3cret')
    const queryClient = mount()
    const stale = ['runs'] as const
    queryClient.setQueryData(stale, { seen: 'as nobody' })

    await userEvent.type(screen.getByLabelText('operator token'), 's3cret')
    await userEvent.click(screen.getByRole('button', { name: 'save token' }))

    await waitFor(() => {
      expect(
        queryClient.getQueryData<Me>(meQueryOptions().queryKey)?.authenticated,
      ).toBe(true)
    })
    expect(fetchMock).toHaveBeenCalled()
    expect(queryClient.getQueryState(stale)?.isInvalidated).toBe(true)
    // The refusal that raised the screen was about the old credential.
    expect(useUi.getState().needsToken).toBe(false)
  })

  it('says so when the token this browser holds was refused', async () => {
    serve('s3cret')
    mount()

    await userEvent.type(screen.getByLabelText('operator token'), 'wrong')
    await userEvent.click(screen.getByRole('button', { name: 'save token' }))

    expect(
      await screen.findByText(/refused the token this browser holds/),
    ).toBeInTheDocument()
    expect(usePrefs.getState().token).toBe('wrong')
    expect(screen.getByLabelText('operator token')).toHaveValue('')
  })

  it('forgets a token on the operator’s word, and asks for one again', async () => {
    serve('s3cret')
    mount({ ...NETWORK, authenticated: true })
    usePrefs.setState({ token: 'stale-from-another-deployment' })

    await userEvent.click(await screen.findByRole('button', { name: 'forget it' }))

    expect(usePrefs.getState().token).toBeNull()
    expect(screen.queryByRole('button', { name: 'forget it' })).toBeNull()
    expect(screen.getByRole('dialog', { name: 'token required' })).toBeInTheDocument()
  })

  it('offers nothing to forget when this browser holds no token', () => {
    serve('s3cret')
    mount()

    expect(screen.queryByRole('button', { name: 'forget it' })).toBeNull()
  })
})

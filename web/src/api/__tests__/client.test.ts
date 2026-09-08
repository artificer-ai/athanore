import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  API_BASE_URL,
  QUERY_RETRIES,
  STALE_TIME_MS,
  createAppQueryClient,
  meQueryOptions,
} from '../client'
import { client } from '../gen/client.gen'
import type { Me } from '../gen/types.gen'
import { usePrefs } from '../../store/prefs'
import { useUi } from '../../store/ui'

const LOOPBACK: Me = {
  auth: 'off',
  authenticated: true,
  features: [],
  started_at: '2026-09-08T09:00:00Z',
  version: '0.1.0',
}

const NETWORK: Me = { ...LOOPBACK, auth: 'token', authenticated: true }

/** Answer every request with `status`, and record the `Request` sent. */
function stubFetch(status = 200) {
  const fetchMock = vi.fn(
    async (_request: Request) =>
      new Response('{}', {
        status,
        headers: { 'Content-Type': 'application/json' },
      }),
  )
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

/** The `Request` the client built for its nth call. */
function sent(fetchMock: ReturnType<typeof stubFetch>, index = 0): Request {
  const request = fetchMock.mock.calls[index]?.[0]
  if (!request) throw new Error(`the client made no request ${index}`)
  return request
}

describe('the API client', () => {
  beforeEach(() => {
    usePrefs.setState({ token: null })
    useUi.setState({ needsToken: false })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('talks to this origin, so a path is the whole URL', async () => {
    createAppQueryClient()
    const fetchMock = stubFetch()

    expect(client.getConfig().baseUrl).toBe(API_BASE_URL)

    await client.get({ url: '/api/runs' })
    expect(sent(fetchMock).url).toBe(`${window.location.origin}/api/runs`)
  })

  it('gives every query the defaults of 10 §Realtime and caching', () => {
    const queryClient = createAppQueryClient()

    const queries = queryClient.getDefaultOptions().queries
    expect(queries?.staleTime).toBe(STALE_TIME_MS)
    expect(queries?.retry).toBe(QUERY_RETRIES)
    expect(STALE_TIME_MS).toBe(5000)
    expect(QUERY_RETRIES).toBe(1)
  })

  describe('the credential', () => {
    it('stops sending it once the server says auth is off', async () => {
      const queryClient = createAppQueryClient()
      queryClient.setQueryData(meQueryOptions().queryKey, LOOPBACK)
      usePrefs.setState({ token: 'left-over-from-somewhere-else' })
      const fetchMock = stubFetch()

      await client.get({ url: '/api/runs' })

      expect(sent(fetchMock).headers.get('Authorization')).toBeNull()
    })

    it('sends the stored token as a bearer header when the server wants one', async () => {
      const queryClient = createAppQueryClient()
      queryClient.setQueryData(meQueryOptions().queryKey, NETWORK)
      usePrefs.setState({ token: 's3cret' })
      const fetchMock = stubFetch()

      await client.get({ url: '/api/runs' })

      expect(sent(fetchMock).headers.get('Authorization')).toBe('Bearer s3cret')
    })

    it('sends nothing when the server wants a token and none is stored', async () => {
      const queryClient = createAppQueryClient()
      queryClient.setQueryData(meQueryOptions().queryKey, NETWORK)
      const fetchMock = stubFetch()

      await client.get({ url: '/api/runs' })

      expect(sent(fetchMock).headers.get('Authorization')).toBeNull()
    })

    it('carries the token on the handshake, which is what makes /api/me answerable', async () => {
      // Nothing has answered yet, so nothing has said the token is
      // unwanted — and `authenticated` is a fact about the request that
      // asks (08 §System), so withholding it here would report a good
      // token as no token on every reload (D154).
      createAppQueryClient()
      usePrefs.setState({ token: 's3cret' })
      const fetchMock = stubFetch()

      await client.get({ url: '/api/me' })

      expect(sent(fetchMock).headers.get('Authorization')).toBe('Bearer s3cret')
    })

    it('sends nothing before /api/me has answered when there is no token', async () => {
      createAppQueryClient()
      const fetchMock = stubFetch()

      await client.get({ url: '/api/me' })

      expect(sent(fetchMock).headers.get('Authorization')).toBeNull()
    })
  })

  describe('the refusal', () => {
    it('asks for a token after a 401', async () => {
      createAppQueryClient()
      const fetchMock = stubFetch(401)

      await client.get({ url: '/api/runs' })

      expect(fetchMock).toHaveBeenCalledOnce()
      expect(useUi.getState().needsToken).toBe(true)
    })

    it('leaves the app alone on any other status', async () => {
      createAppQueryClient()
      stubFetch(403)

      await client.get({ url: '/api/runs' })

      expect(useUi.getState().needsToken).toBe(false)
    })
  })

  it('replaces its wiring rather than stacking it, one client per app', async () => {
    createAppQueryClient()
    const queryClient = createAppQueryClient()
    queryClient.setQueryData(meQueryOptions().queryKey, NETWORK)
    usePrefs.setState({ token: 's3cret' })
    const fetchMock = stubFetch()

    await client.get({ url: '/api/runs' })

    // The second client's cache is the one read, and the first client's
    // interceptors are gone rather than running first.
    expect(sent(fetchMock).headers.get('Authorization')).toBe('Bearer s3cret')
    expect(client.interceptors.request.fns).toHaveLength(1)
    expect(client.interceptors.response.fns).toHaveLength(1)
  })
})

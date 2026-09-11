/**
 * The SPA's one way to the server: the generated fetch client, wired to
 * this origin, and the TanStack Query client that caches what it fetches.
 *
 * Nothing in the app calls `fetch` itself. The client, its types and its
 * query options are generated from the committed OpenAPI snapshot
 * (`src/api/gen`, T008), so a change to the wire contract is a failed
 * typecheck rather than a runtime surprise — which is the whole of 02
 * §One wire contract on this side of it.
 *
 * Two interceptors are all the policy there is:
 *
 * - **the credential.** The stored token goes out as a bearer header on
 *   every request, `/api/me` included: `authenticated` is a fact about
 *   the request that asks (08 §System), so a header withheld until the
 *   mode is known would report a good token as no token on every reload
 *   (D154). The one server it is withheld from is the one that has
 *   answered `auth: "off"` — on a plain loopback bind the operator has
 *   nothing to prove (12 §Operator token), so a token `localStorage`
 *   still holds from some other deployment reaches it once, is ignored,
 *   and is never sent again.
 * - **the refusal.** A 401 from anywhere means the token this browser
 *   holds is missing or no longer good, and the app owes the operator
 *   the token screen (10 §Auth in the browser).
 */
import { QueryClient, useQuery } from '@tanstack/react-query'

import { usePrefs } from '../store/prefs'
import { useUi } from '../store/ui'
import { meApiMeGetOptions } from './gen/@tanstack/react-query.gen'
import { client } from './gen/client.gen'
import type { Me } from './gen/types.gen'

/**
 * The SPA is served by the Athanore server at `/`, so every request is
 * same-origin and relative: `""` is what makes `/api/runs` mean this
 * server both in the built bundle and behind the Vite dev server's proxy
 * (`vite.config.ts`).
 */
export const API_BASE_URL = ''

/**
 * How long a fetched resource is served from cache without refetching.
 *
 * Freshness comes from SSE (T060), not from a clock: five seconds is
 * only what keeps the several components that read one resource on a
 * single request.
 */
export const STALE_TIME_MS = 5000

/**
 * One retry, and no more. The server is on localhost, so a request that
 * failed twice failed because the server is not there — and a retry
 * storm against a paused or restarting server helps nobody.
 */
export const QUERY_RETRIES = 1

/** The HTTP status that means "prove who you are". */
export const UNAUTHORIZED = 401

/**
 * The query client the fetch client reads its credential out of.
 *
 * Held here so that {@link apiAuthHeaders} can answer the same question
 * the request interceptor does, from the same cache, without either of
 * them owning a second copy of `/api/me`. Set by
 * {@link createAppQueryClient} and replaced when a second app is
 * mounted, which is the same lifetime the interceptors have.
 */
let configured: QueryClient | null = null

/**
 * The `Authorization` header this server wants, or none at all.
 *
 * **One rule, in one place.** The interceptor below applies it to every
 * typed call, and `window.athanore.fetch` applies it to the calls a
 * plugin's web component makes (09 §Escape hatch) — and a plugin route
 * is an operator route (12 §Plugins), so the two must not be able to
 * disagree about when a credential is sent. The rule is D154's: the
 * stored token goes out on everything, including `/api/me`, and is
 * withheld only from a server that has already answered `auth: "off"`.
 */
export function apiAuthHeaders(): Record<string, string> {
  const me = configured?.getQueryData<Me>(meQueryOptions().queryKey)
  const token = usePrefs.getState().token
  if (token === null || me?.auth === 'off') return {}
  return { Authorization: `Bearer ${token}` }
}

/**
 * Report a refusal the way the response interceptor does.
 *
 * A 401 from anywhere means the token this browser holds is missing or
 * no longer good — from a plugin's own request as much as from a typed
 * one, since both go through the same door.
 */
export function reportUnauthorized(status: number): void {
  if (status === UNAUTHORIZED) useUi.getState().setNeedsToken(true)
}

/**
 * The query options for `GET /api/me` — what this server wants and
 * whether this caller has it (08 §System).
 *
 * A function rather than a constant because the key the generator builds
 * carries the client's `baseUrl`: computed at module load it would carry
 * whatever the config held before {@link createAppQueryClient} ran, and
 * the interceptor below would then read a cache entry nobody writes.
 */
export function meQueryOptions() {
  return meApiMeGetOptions()
}

/**
 * `/api/me`, cached: the one query `AppGate` gates the app on.
 *
 * `queryFn` is put back explicitly because `queryOptions` declares it
 * optional and `tsconfig.app.json` sets `exactOptionalPropertyTypes`, so
 * the whole object is not assignable to `useQuery`'s parameter as it
 * stands. The generator always sets it — that is what the `!` says — and
 * the rest of the options travel untouched.
 */
export function useMe() {
  const { queryFn, ...options } = meQueryOptions()
  return useQuery({ ...options, queryFn: queryFn! })
}

/**
 * Point the generated client at this origin and give it its two
 * interceptors, reading the auth mode out of `queryClient`'s cache.
 *
 * The cache is the only copy of `/api/me` there is: mirroring `auth`
 * into a store would be a second one, and a second one can be stale.
 * The first request the app makes is the one that finds out whether a
 * credential is wanted, and it carries whatever token this browser
 * holds so that the answer can say whether that token is any good.
 *
 * Idempotent: the interceptor lists are cleared before they are filled,
 * so a second query client (a test, a remount) replaces the wiring of
 * the first rather than stacking a second copy of it on top.
 */
function configureApiClient(queryClient: QueryClient): void {
  client.setConfig({ baseUrl: API_BASE_URL })
  configured = queryClient

  client.interceptors.request.clear()
  client.interceptors.response.clear()

  client.interceptors.request.use((request) => {
    // Withheld from a server that has said it does not want it, and from
    // no other: before `/api/me` has answered, the credential is what
    // makes its answer worth having, and `/api/me` never refuses one.
    for (const [header, value] of Object.entries(apiAuthHeaders())) {
      request.headers.set(header, value)
    }
    return request
  })

  client.interceptors.response.use((response) => {
    reportUnauthorized(response.status)
    return response
  })
}

/**
 * The app's query client, with the generated fetch client wired to it.
 *
 * The two are made together because they are two halves of one thing:
 * the fetch client's credential comes out of this cache, so a query
 * client that was never handed to {@link configureApiClient} would send
 * unauthenticated requests on a server that wants a token.
 */
export function createAppQueryClient(): QueryClient {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: STALE_TIME_MS,
        retry: QUERY_RETRIES,
      },
    },
  })
  configureApiClient(queryClient)
  return queryClient
}

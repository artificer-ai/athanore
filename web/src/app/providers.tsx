/**
 * The providers the whole app sits inside.
 *
 * One of them, for now: TanStack Query, whose cache is the SPA's copy of
 * every server resource (`docs/v1/10-frontend.md` §Stack). The router is
 * mounted underneath it rather than around it, because `AppGate` decides
 * whether there is an app to route at all — and it decides that from a
 * query.
 *
 * The defaults are `src/api/client.ts`'s, and the client it makes is the
 * one the generated fetch client reads its credential from, so there is
 * exactly one query client per mounted app and nothing that can drift
 * from it.
 */
import { useState, type ReactNode } from 'react'
import { QueryClientProvider, type QueryClient } from '@tanstack/react-query'

import { createAppQueryClient } from '../api/client'

/**
 * Wrap `children` in the app's providers.
 *
 * A `client` may be passed in — a test that wants to seed or read the
 * cache needs a handle on it. When none is, one is made on first render
 * and kept for the life of the mount.
 */
export function Providers({
  client,
  children,
}: {
  client?: QueryClient
  children: ReactNode
}) {
  const [queryClient] = useState(() => client ?? createAppQueryClient())

  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}

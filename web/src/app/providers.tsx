/**
 * The providers the whole app sits inside.
 *
 * One of them, for now: TanStack Query, whose cache is the SPA's copy of
 * every server resource. The router is mounted underneath it rather
 * than around it, because `AppGate` decides whether there is an app to
 * route at all — and it decides that from a query.
 *
 * The defaults are `src/api/client.ts`'s, and the client it makes is the
 * one the generated fetch client reads its credential from, so there is
 * exactly one query client per mounted app and nothing that can drift
 * from it.
 *
 * The event feed is opened here for the same reason: it keeps that one
 * cache fresh (10 §Realtime and caching), it is one stream per tab, and
 * a mount is exactly as long as it should live.
 *
 * `Toaster` is here for a third form of the same reason: 10 §Components
 * gives the app one toast surface, and a component that raises a toast
 * has to find it wherever it is mounted (`components/ui/sonner.tsx`).
 */
import { useEffect, useState, type ReactNode } from 'react'
import { QueryClientProvider, type QueryClient } from '@tanstack/react-query'

import { createAppQueryClient } from '../api/client'
import { Toaster } from '../components/ui/sonner'
import { createAppEventFeed } from '../realtime/sse'

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

  // Made inside the effect rather than in state: `StrictMode` invokes a
  // state initialiser twice and keeps one of the two results, which
  // would leave the tab's feed and the started feed as different
  // objects. An effect is mounted, torn down and mounted again, so the
  // one that survives is the one that ran last.
  useEffect(() => {
    const feed = createAppEventFeed(queryClient)
    feed.start()
    return () => feed.stop()
  }, [queryClient])

  return (
    <QueryClientProvider client={queryClient}>
      {children}
      <Toaster />
    </QueryClientProvider>
  )
}

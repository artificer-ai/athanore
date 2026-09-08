/**
 * The plugin manifest: everything the browser knows about panes.
 *
 * `GET /api/plugins` is the whole of it (`docs/v1/09-plugins.md` §Wire
 * contract) — the builtins included, because the core's own panes are
 * declared through the same API (09 §Builtins are plugins). It is
 * fetched at boot and again whenever the event feed reconnects to a
 * process with a new `started_at`: the manifest only changes on restart,
 * so there is no event for it, and `src/realtime/sse.ts` is what
 * refetches it.
 */
import { useQuery } from '@tanstack/react-query'

import { manifestApiPluginsGetOptions } from '../api/gen/@tanstack/react-query.gen'
import type { PluginManifestEntry } from '../api/gen/types.gen'

/** The manifest entry the core's own panes are declared on (09). */
export const BUILTIN_WORKFLOW = '_builtin'

/**
 * `GET /api/plugins`, cached.
 *
 * `queryFn` is put back explicitly for the reason `useMe` does it
 * (`src/api/client.ts`): the generator declares it optional and
 * `exactOptionalPropertyTypes` will not assign an optional-and-absent
 * property onto `useQuery`'s required one.
 */
export function useManifestQuery() {
  const { queryFn, ...options } = manifestApiPluginsGetOptions()
  return useQuery({ ...options, queryFn: queryFn! })
}

/** The manifest, as the pane host reads it. */
export function useManifest(): {
  manifest: PluginManifestEntry[]
  isPending: boolean
  isError: boolean
} {
  const { data, isPending, isError } = useManifestQuery()

  // `Array.isArray` rather than `?? []`: the manifest is the one
  // resource whose absence has to be told from a server that answered
  // with something else entirely (a proxy's error page, say), and a pane
  // host that trusted the shape would throw where 09 wants a degradation.
  return { manifest: Array.isArray(data) ? data : [], isPending, isError }
}

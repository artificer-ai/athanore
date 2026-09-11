/**
 * The plugin manifest: everything the browser knows about panes.
 *
 * `GET /api/plugins` is the whole of it — the builtins included, because
 * the core's own panes are declared through the same API (09 §Builtins
 * are plugins). It is fetched at boot, again whenever the event feed
 * reconnects to a process with a new `started_at` (`src/realtime/sse.ts`
 * refetches it: a restart is the one change no event announces), and
 * on every `workflow.*` — a registration, a reload or a removal changes
 * what the manifest lists, and the invalidation table's row for those
 * names is what refetches it (22 §SPA, `src/realtime/invalidate.ts`).
 *
 * Reading it is also what registers the panels' `refresh_on` names in
 * the invalidation table — "at manifest load" (10 §Realtime and
 * caching), which is here and nowhere else, so a manifest that is
 * replaced replaces the registrations with it. And it is where the one
 * thing a document cannot follow is noticed: a workflow reloaded with
 * different JavaScript lists its asset at a new `?v=`, and a module this
 * page already ran cannot run again. {@link useStaleAssets} finds those
 * URLs at manifest load — here, not only when a custom pane happens to
 * mount, because a pane viewed earlier and cycled away from has its
 * module in the document all the same — and puts them where the shell's
 * notice reads them (`store/ui.ts`, `components/PluginAssetsBanner.tsx`).
 */
import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo } from 'react'

import { manifestApiPluginsGetOptions } from '../api/gen/@tanstack/react-query.gen'
import type { PluginManifestEntry } from '../api/gen/types.gen'
import { staleAssets } from '../plugins'
import { useUi } from '../store/ui'
import { usePanelRefreshRegistry } from './source'

/** The manifest entry the core's own panes are declared on (09). */
export const BUILTIN_WORKFLOW = '_builtin'

/**
 * The manifest before one has arrived — one array, not a fresh `[]` per
 * render, so the registration effect below fires on a manifest that
 * changed rather than on every render that has none.
 */
const EMPTY: PluginManifestEntry[] = []

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

/** What a reader of the manifest gets, whatever it asked for. */
export type ManifestRead = {
  manifest: PluginManifestEntry[]
  isPending: boolean
  isError: boolean
}

/**
 * The manifest, read and nothing more.
 *
 * `Array.isArray` rather than `?? []`: the manifest is the one resource
 * whose absence has to be told from a server that answered with
 * something else entirely (a proxy's error page, say), and a pane host
 * that trusted the shape would throw where 09 wants a degradation.
 *
 * Separate from {@link useManifest} because reading the manifest and
 * *registering* what it says are two things, and only one of them may
 * happen once: the `refresh_on` table is global and is cleared before it
 * is rebuilt (`./source.ts`), so the several surfaces that look an
 * action or a panel up — a `form` pane, the action overlay — read
 * through here and leave the registration to the pane host.
 */
export function useManifestEntries(): ManifestRead {
  const { data, isPending, isError } = useManifestQuery()
  const manifest = useMemo(() => (Array.isArray(data) ? data : EMPTY), [data])
  return { manifest, isPending, isError }
}

/**
 * Mark, for each workflow the manifest lists, the asset URLs this
 * document cannot follow (22 §SPA).
 *
 * Keyed on the manifest, so it runs once per manifest that arrived and
 * not per render. A first load finds nothing injected, an identical
 * refetch finds every URL loaded as listed, and a removed workflow lists
 * nothing — all three are empty and mark nothing (`plugins/assets.ts`).
 */
export function useStaleAssets(manifest: readonly PluginManifestEntry[]): void {
  const markStaleAssets = useUi((state) => state.markStaleAssets)
  useEffect(() => {
    for (const entry of manifest) {
      const stale = staleAssets(entry.assets ?? [])
      if (stale.length > 0) markStaleAssets(entry.workflow, stale)
    }
  }, [manifest, markStaleAssets])
}

/**
 * The manifest, as the pane host reads it: read, registered, and
 * checked against what this document has already run.
 */
export function useManifest(): ManifestRead {
  const read = useManifestEntries()
  usePanelRefreshRegistry(read.manifest)
  useStaleAssets(read.manifest)
  return read
}

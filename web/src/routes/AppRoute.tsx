/**
 * The components the route tree mounts (`./router.tsx`).
 *
 * They live beside it rather than in it so that neither file mixes
 * component exports with the route objects, which is what React Fast
 * Refresh needs to keep either of them updatable in place.
 */
import { useEffect } from 'react'
import { useNavigate, useSearch } from '@tanstack/react-router'

import App from '../App'

/** Route `/`: the app shell, over the search parameters it validated. */
export function AppRoute() {
  const search = useSearch({ from: '/' })
  const navigate = useNavigate({ from: '/' })

  return (
    <App
      search={search}
      onSelectRun={(runId) => {
        // Selection is the URL (10 §Layout): the run list holds none of
        // its own, so a click and a pasted link end in the same state.
        void navigate({ search: (prev) => ({ ...prev, run: runId }) })
      }}
      onOpenPalette={() => {
        // The palette itself is T066a; the state it opens from is this
        // task's, and it is a search parameter like every other overlay.
        void navigate({ search: (prev) => ({ ...prev, overlay: 'palette' }) })
      }}
    />
  )
}

/**
 * Anything that is not `/` is not a view of this app — the whole SPA is
 * one route plus search parameters — so a stale path is replaced with
 * `/` rather than shown as an error page.
 */
export function NotFoundRedirect() {
  const navigate = useNavigate()

  useEffect(() => {
    void navigate({ to: '/', search: {}, replace: true })
  }, [navigate])

  return null
}

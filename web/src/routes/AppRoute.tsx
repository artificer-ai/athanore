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
        // `?node=` goes with it: a node filter is one run's graph, and
        // carrying it to the next run would filter that run's log to a
        // node it may not have.
        void navigate({ search: (prev) => ({ ...prev, run: runId, node: undefined }) })
      }}
      onSelectPane={(index) => {
        // The pane index is a search parameter like the selection (10
        // §Layout: `?run=&pane=`), so a link carries which pane was
        // open, and the pane host clamps whatever it is given.
        void navigate({ search: (prev) => ({ ...prev, pane: index }) })
      }}
      onOpenPalette={() => {
        // The palette itself is T066a; the state it opens from is this
        // task's, and it is a search parameter like every other overlay.
        void navigate({ search: (prev) => ({ ...prev, overlay: 'palette' }) })
      }}
      onFilterNode={(node) => {
        // `?node=` filters the event log (10 §Panes item 2). The graph
        // pane writes it and the pane's own control clears it, both
        // through here, so a filtered log is a link like every other
        // view of this app.
        void navigate({ search: (prev) => ({ ...prev, node }) })
      }}
      onOpenTask={(taskId) => {
        // The task drawer is `?overlay=task&task=`, the pair 10 §Layout
        // names: the overview's NODES rows and the graph's rows open it
        // by writing the search, and the drawer itself is T066e.
        void navigate({
          search: (prev) => ({ ...prev, overlay: 'task', task: taskId }),
        })
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

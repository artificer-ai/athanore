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
        // node it may not have. `?global=` goes too: selecting a run is
        // how the detail stops showing the global panes and starts
        // showing the run's, and below the breakpoint that is the same
        // one navigation off the global screen (21 §Narrow layout, D216).
        void navigate({
          search: (prev) => ({ ...prev, run: runId, node: undefined, global: undefined }),
        })
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
      onOpenNode={(node, pane) => {
        // One navigation and not two: 10 §Graph pane's "jumps to the log
        // pane filtered to that node" is `?node=` and `?pane=` together,
        // and writing them in two calls would leave the second updating
        // a search the first had already replaced. It names a run pane
        // by index, so the narrow global screen comes down with it
        // (D216) — a pane index means nothing on a screen that shows a
        // different cycle.
        void navigate({
          search: (prev) => ({
            ...prev,
            node,
            global: undefined,
            ...(pane === undefined ? {} : { pane }),
          }),
        })
      }}
      onOpenOverlay={(overlay) => {
        // Every overlay is `?overlay=` (10 §Layout); the graph pane's
        // `open definition` opens the library on the selected run's
        // workflow, which `?run=` already names. The overlays themselves
        // are T066a–T066e.
        void navigate({ search: (prev) => ({ ...prev, overlay }) })
      }}
      onOpenAction={(action) => {
        // `?overlay=action&action=<workflow>:<name>`, in one navigation:
        // writing the next overlay is what closes the palette, and the
        // action it is about is a parameter of its own because
        // `?overlay=` names the overlay and not its subject (T070).
        void navigate({
          search: (prev) => ({ ...prev, overlay: 'action', action }),
        })
      }}
      onCloseOverlay={() => {
        // Closing is the same one parameter, written away: `esc` and a
        // click on the backdrop both end here, so the URL is what says
        // whether an overlay is up and the back button works on it.
        // `?action=` goes with it, because the action overlay is the
        // only thing that reads it — unlike `?task=`, which outlives the
        // drawer as the agent pane's focused attempt.
        void navigate({
          search: (prev) => ({ ...prev, overlay: undefined, action: undefined }),
        })
      }}
      onOpenTask={(taskId) => {
        // The task drawer is `?overlay=task&task=`, the pair 10 §Layout
        // names: the overview's NODES rows, the graph's rows and the
        // drawer's own lineage links open it by writing the search.
        void navigate({
          search: (prev) => ({ ...prev, overlay: 'task', task: taskId }),
        })
      }}
      onFocusStream={(taskId, pane) => {
        // One navigation and not three: the drawer closes, `?task=`
        // stays — it is the agent pane's focused attempt (T063c) — and
        // the cycle moves to that pane. Written separately, the last
        // write would be updating a search the first had replaced. Like
        // `onOpenNode` it names a run pane, so `?global=` goes (D216).
        void navigate({
          search: (prev) => ({
            ...prev,
            overlay: undefined,
            task: taskId,
            global: undefined,
            ...(pane === undefined ? {} : { pane }),
          }),
        })
      }}
      onShowGlobal={(index) => {
        // The narrow global screen (21 §Narrow layout, D216): `?global=`
        // is the global cycle's own index, present while the screen is
        // up. `undefined` is how it is left — the router drops the key,
        // as it does for `overlay` — and `?run=` and `?pane=` are not
        // touched either way, which is what lands a swipe back on the
        // pane of the run the operator was on.
        void navigate({ search: (prev) => ({ ...prev, global: index }) })
      }}
      onClearRun={() => {
        // Nothing is selected any more. Two callers say that: the
        // delete confirm, once the run is gone — a selection that no
        // longer exists would point the detail pane at a 404 — and the
        // pane bar's narrow back control, for which "back to the list"
        // *is* "nothing is selected" (21 §Narrow layout). Either way
        // `?node=` and `?task=` were about that run too.
        void navigate({
          search: (prev) => ({
            ...prev,
            run: undefined,
            node: undefined,
            task: undefined,
          }),
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

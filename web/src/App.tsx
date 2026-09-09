/**
 * The app shell: the four regions of `docs/v1/10-frontend.md` §Layout —
 * header, run list, detail, footer.
 *
 * The list and the detail pane sit either side of `Splitter`, which owns
 * the width between them and the rail the list collapses to.
 *
 * Everything that makes this view *this view* comes in on `search`: the
 * shell owns no selection state of its own, and `onSelectRun` hands a
 * click back to the route, which writes `?run=`.
 *
 * `GET /api/runs` is read once, here, and shared: the header's counts,
 * the chips, the rows and the collapsed rail's `RUNS n` are four views of
 * one cached resource, so they cannot disagree and they refresh together
 * when `run.*` or `task.*` invalidates it (10 §Realtime and caching).
 *
 * `ServerDownBanner` sits directly under the header and renders nothing
 * while the event feed is up (10 §Realtime and caching).
 *
 * `useAttention` is read here for a third form of the same reason: the
 * tab title and the desktop notifications are one fact about the whole
 * app (10 §Attention), and the shell is the one component mounted for
 * exactly as long as the app is.
 *
 * `usePanes` is read here rather than inside `Detail` for the same
 * reason `GET /api/runs` is: the pane cycle's actions are the keyboard's
 * too (`←`, `→`, `1`–`9`, T067) and the palette's as well — `append log`
 * is "the log pane, with the caret in its composer" — and a shell that
 * holds the model can hand it to all of them without any of them owning
 * the others.
 *
 * `useKeymap` is bound here for the same reason and reads the same three
 * models: 10 §Keyboard is one map over the whole app, and every action
 * in it is already in this function — the palette's catalogue, the pane
 * cycle, and the selection the route writes (`src/keys/useKeymap.ts`).
 *
 * The overlays hang off the shell rather than off whatever opened them,
 * because `?overlay=` is one piece of state and the thing it names is
 * over the whole app (10 §Overlays). They portal out of this tree, so
 * where they sit in it says nothing about where they draw. The header's
 * `＋ new run` is one more way of writing `?overlay=new`, and its
 * `workflows` is one more way of writing `?overlay=library`, beside the
 * palette's rows and (T067) the `n` and `w` keys.
 */
import { useQueryClient } from '@tanstack/react-query'
import { useRef } from 'react'

import { Detail } from './components/Detail'
import { Footer } from './components/Footer'
import { Header } from './components/Header'
import { RunList, useRunListModel, useRuns } from './components/RunList'
import { ServerDownBanner } from './components/ServerDownBanner'
import { Splitter } from './components/Splitter'
import { useAttention } from './components/attention'
import { useKeymap } from './keys'
import {
  DeleteRun,
  EditRun,
  Keys,
  Library,
  NewRun,
  Palette,
  Pickers,
  PluginAction,
  TaskDrawer,
  buildPaletteActions,
  pauseDirection,
  pluginPaletteActions,
  useRunOps,
} from './overlays'
import { BUILTIN_WORKFLOW, actionsOf, useManifest, usePanes } from './panes'
import type { AppSearch, Overlay } from './routes/search'
import { usePrefs } from './store/prefs'
import { useUi } from './store/ui'

/** What a handler the shell was not given does. */
const NOTHING = () => {}

/** The builtin pane a graph row jumps to (10 §Graph pane, 09 §Builtins). */
const LOG_PANE = 'log'

/** The builtin pane the task drawer's `focus stream` jumps to (T063c). */
const AGENT_PANE = 'agent'

export default function App({
  search,
  onSelectRun,
  onSelectPane,
  onOpenPalette,
  onOpenTask,
  onFilterNode,
  onOpenNode,
  onOpenOverlay,
  onOpenAction,
  onCloseOverlay,
  onFocusStream,
  onClearRun,
}: {
  search: AppSearch
  onSelectRun: (runId: string) => void
  onSelectPane: (index: number) => void
  onOpenPalette: () => void
  onOpenTask?: ((taskId: number) => void) | undefined
  onFilterNode?: ((node: string | undefined) => void) | undefined
  /**
   * `?node=` and `?pane=` in one navigation: a graph row "jumps to the
   * log pane filtered to that node" (10 §Graph pane), and the shell is
   * where the log pane's index is known.
   */
  onOpenNode?: ((node: string, pane: number | undefined) => void) | undefined
  /** Open an overlay by name; the graph's `open definition` opens one. */
  onOpenOverlay?: ((overlay: Overlay) => void) | undefined
  /**
   * Run a plugin's action: `?overlay=action&action=<workflow>:<name>`.
   *
   * One navigation, like every overlay command — writing the next
   * overlay is what closes the palette (`overlays/actions.ts`) — and one
   * parameter more, because which action it is about is not something
   * `?overlay=` can say (10 §Layout).
   */
  onOpenAction?: ((action: string) => void) | undefined
  /** Close whichever overlay is up: `?overlay=` away (10 §Overlays). */
  onCloseOverlay?: (() => void) | undefined
  /**
   * The task drawer's `focus stream`: show `taskId`'s transcript.
   *
   * One navigation and not three — `?overlay=` away, `?task=` kept, and
   * the agent pane's index — because the drawer is closing onto the pane
   * it is handing over to, and three writes would leave the last one
   * updating a search the first had already replaced.
   */
  onFocusStream?: ((taskId: number, pane: number | undefined) => void) | undefined
  /**
   * Nothing is selected any more: `?run=` away.
   *
   * The delete confirm is the one thing that calls it. A run that no
   * longer exists cannot be the selection, and leaving `?run=` on a
   * deleted id would point the detail pane at a 404.
   */
  onClearRun?: (() => void) | undefined
}) {
  const runs = useRunListModel()
  useAttention()
  const panes = usePanes(search.run, { index: search.pane, onChange: onSelectPane })
  const queryClient = useQueryClient()
  const toggleListCollapsed = usePrefs((state) => state.toggleListCollapsed)
  const setFontSize = usePrefs((state) => state.setFontSize)
  const focusLogComposer = useUi((state) => state.focusLogComposer)
  const setFocus = useUi((state) => state.setFocus)
  const detail = useRef<HTMLElement | null>(null)

  // Which pane the log is, in *this* selection's cycle: the manifest
  // decides how many panes there are and a plugin's `log` panel is not
  // this one, so the index is looked up rather than assumed (09
  // §Builtins are plugins).
  const logPane = panes.panes.findIndex(
    (pane) => pane.workflow === BUILTIN_WORKFLOW && pane.name === LOG_PANE,
  )
  const agentPane = panes.panes.findIndex(
    (pane) => pane.workflow === BUILTIN_WORKFLOW && pane.name === AGENT_PANE,
  )

  // The status that decides whether `p` pauses the selected run,
  // resumes it, or is disabled (`overlays/runOps.ts`). It is read off
  // the same `GET /api/runs` entry the list draws from — the whole
  // entry, not `runs.rows`, because the header's chip and its `/` input
  // narrow those and a run the operator has filtered out of sight is
  // still the selected one.
  const selected = useRuns().data?.find((run) => run.id === search.run)
  const runOps = useRunOps()
  // The manifest the palette's plugin rows come from. Already cached —
  // the pane host read it a moment ago — so this costs no request, and
  // reading it here is what keeps the palette's catalogue in one place.
  const { manifest } = useManifest()

  // The palette's rows are the app's own actions, so they are built here
  // rather than inside it: `refresh` is this tab's whole cache,
  // `toggle list` is the splitter's rail, and `append log` is the pane
  // cycle plus the caret — the shell is where all three are already in
  // hand (`overlays/actions.ts`).
  //
  // The manifest's actions join them under `plugin: <workflow>` (09
  // §Declarations): what a workflow contributes is the *server's* to
  // say, so the rows arrive from `GET /api/plugins` and are filtered by
  // the same ownership rule the panes are — the builtins' and the
  // selected run's workflow's (`panes/actions.ts`).
  const paletteActions = buildPaletteActions({
    runId: search.run,
    openOverlay: onOpenOverlay ?? NOTHING,
    close: onCloseOverlay ?? NOTHING,
    refresh: () => {
      void queryClient.invalidateQueries()
    },
    toggleList: toggleListCollapsed,
    // `append log` writes nothing itself: the note is the log pane's
    // composer, which already posts it (`panes/kinds/Log.tsx`), so the
    // command is "show me that box and put me in it". The caret is asked
    // for through `useUi` because the composer is mounted by the pane
    // once its panel has answered, which is after this call returns; a
    // cycle with no log pane in it — a manifest still in flight — asks
    // for nothing rather than leaving a request nothing will serve.
    appendLog: () => {
      if (logPane < 0 || search.run === undefined) return
      panes.jump(logPane)
      focusLogComposer(search.run)
    },
    pauseResume: () => {
      if (search.run === undefined) return
      runOps.pauseResume(search.run, selected?.status)
    },
    canPauseResume: pauseDirection(selected?.status) !== null,
    cancelRun: () => {
      if (search.run === undefined) return
      runOps.cancel(search.run)
    },
    reorder: (direction) => {
      if (search.run === undefined) return
      runOps.reorder(search.run, direction)
    },
    // The header's chooser writes the same pref (21 §Type scale); the
    // rows exist so the choice is reachable without a pointer (D196).
    setFontSize,
  }).concat(
    pluginPaletteActions(
      actionsOf(manifest, { runId: search.run, workflow: selected?.workflow }),
      { runId: search.run, taskId: search.task },
      onOpenAction ?? NOTHING,
    ),
  )

  // 10 §Keyboard, bound to exactly the model above. Fourteen of its keys
  // are the palette's rows and are dispatched on that catalogue's key
  // column; what is left is navigation, which no palette row can be.
  useKeymap({
    actions: paletteActions,
    // The mock's `move`: clamped rather than wrapping, so holding `j` at
    // the bottom of the list stays there instead of jumping to the top.
    // With nothing selected, `↓` takes the first row and `↑` the last.
    select: (delta) => {
      const rows = runs.rows
      if (rows.length === 0) return
      const at = rows.findIndex((row) => row.id === search.run)
      const to =
        at < 0
          ? delta > 0
            ? 0
            : rows.length - 1
          : Math.min(Math.max(at + delta, 0), rows.length - 1)
      const row = rows[to]
      if (row !== undefined && row.id !== search.run) onSelectRun(row.id)
    },
    cyclePane: (delta) => {
      if (delta > 0) panes.next()
      else panes.prev()
    },
    jumpPane: panes.jump,
    // `⏎ focus detail`: the region the keystrokes go to (`store/ui.ts`)
    // and the element that holds the browser's focus, which are two
    // halves of one move.
    focusDetail: () => {
      setFocus('detail')
      detail.current?.focus()
    },
    openPalette: onOpenPalette,
    // `esc close`: there is nothing to close with no overlay up, and a
    // navigation that rewrote the same search would be one entry of
    // history per keystroke.
    close: () => {
      if (search.overlay !== undefined) onCloseOverlay?.()
    },
  })

  return (
    <div className="text-body flex h-dvh flex-col overflow-hidden bg-background text-foreground">
      <Header
        runs={runs}
        onNewRun={() => {
          onOpenOverlay?.('new')
        }}
        onOpenLibrary={() => {
          onOpenOverlay?.('library')
        }}
      />
      <ServerDownBanner />

      <Splitter
        count={runs.rows.length}
        list={
          <RunList model={runs} selected={search.run} onSelect={onSelectRun} />
        }
        detail={
          <Detail
            ref={detail}
            panes={panes}
            taskId={search.task}
            node={search.node}
            onOpenTask={onOpenTask}
            onFilterNode={onFilterNode}
            onOpenNode={
              onOpenNode === undefined
                ? undefined
                : (node) => {
                    onOpenNode(node, logPane < 0 ? undefined : logPane)
                  }
            }
            onOpenLibrary={
              onOpenOverlay === undefined
                ? undefined
                : () => {
                    onOpenOverlay('library')
                  }
            }
          />
        }
      />

      <Footer onOpenPalette={onOpenPalette} />

      <Palette
        open={search.overlay === 'palette'}
        actions={paletteActions}
        onClose={onCloseOverlay ?? NOTHING}
      />

      <NewRun open={search.overlay === 'new'} onClose={onCloseOverlay ?? NOTHING} />

      {/* `?run=` says which workflow the library opens on and `?node=`
          which line it lands on, so the graph pane's `open definition`
          hands nothing over that the search does not already carry
          (`overlays/Library.tsx`). */}
      <Library
        open={search.overlay === 'library'}
        runId={search.run}
        node={search.node}
        onClose={onCloseOverlay ?? NOTHING}
      />

      <EditRun
        open={search.overlay === 'edit'}
        runId={search.run}
        onClose={onCloseOverlay ?? NOTHING}
      />

      {/* The four pickers are one overlay: `?overlay=` says which of them
          is up, and each is a list of `?run=`'s attempts or nodes plus
          the one `POST` that list names (`overlays/Pickers.tsx`). */}
      <Pickers
        overlay={search.overlay}
        runId={search.run}
        onClose={onCloseOverlay ?? NOTHING}
      />

      {/* Everything about one attempt, over `?overlay=task&task=`. The
          `?task=` it opens on outlives it: it is also the agent pane's
          focused attempt, which is what `focus stream` hands over to
          (`overlays/TaskDrawer.tsx`). */}
      <TaskDrawer
        open={search.overlay === 'task'}
        taskId={search.task}
        onClose={onCloseOverlay ?? NOTHING}
        onOpenTask={onOpenTask}
        onFocusStream={
          onFocusStream === undefined
            ? undefined
            : (taskId) => {
                onFocusStream(taskId, agentPane < 0 ? undefined : agentPane)
              }
        }
      />

      {/* A plugin's action, from the palette: `?action=` says which one,
          and the form it draws is the action's own model (09). */}
      <PluginAction
        open={search.overlay === 'action'}
        action={search.action}
        runId={search.run}
        taskId={search.task}
        onClose={onCloseOverlay ?? NOTHING}
      />

      <Keys open={search.overlay === 'keys'} onClose={onCloseOverlay ?? NOTHING} />

      {/* The one confirm of 10 §Keyboard: `delete(run)` is the only
          operator op that destroys anything (`overlays/DeleteRun.tsx`). */}
      <DeleteRun
        open={search.overlay === 'delete'}
        runId={search.run}
        onClose={onCloseOverlay ?? NOTHING}
        onDeleted={onClearRun}
      />
    </div>
  )
}

/**
 * The app shell: the four regions of `docs/v1/10-frontend.md` §Layout —
 * header, run list, detail, footer.
 *
 * The list and the detail pane sit either side of `Splitter`, which owns
 * the width between them and the rail the list collapses to. Below the
 * breakpoint there is no width between them: `useIsNarrow` says the
 * viewport is a phone's, and the middle is one region — the list while
 * `?run=` is unset, the detail while it is set (21 §Narrow layout,
 * D194). Selection is already a search parameter, so the stacked
 * navigation is a render decision and not new state, and `onClearRun` —
 * which the delete confirm already had — is what the pane bar's back
 * control writes. A third narrow screen, the **global screen**, sits
 * beside the list: `?global=` set while `?run=` is unset is the same
 * `Detail` over the global cycle — what the desktop draws with nothing
 * selected — entered from the list by a swipe right or the footer's
 * `global panes` button and left by a swipe left, the bar's `←`, the
 * button or `esc`, with `?pane=` untouched (D216, D218). The three
 * screens fan around the list — global | list | detail — and a swipe
 * is one screen along that row: right on the list reaches the global
 * screen, left on the global screen and right on the detail both
 * return to the list, and the detail is entered only by tapping a row.
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
import { useEffect } from 'react'

import { Detail } from './components/Detail'
import { Footer } from './components/Footer'
import { Header } from './components/Header'
import { RunList, useRunListModel, useRuns } from './components/RunList'
import { ServerDownBanner } from './components/ServerDownBanner'
import { Splitter } from './components/Splitter'
import { useAttention } from './components/attention'
import { useKeymap } from './keys'
import { useIsNarrow } from './lib/useIsNarrow'
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
  onShowGlobal,
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
   * Nothing is selected any more: `?run=` away, and `?global=` with it.
   *
   * The delete confirm calls it, and so do the narrow detail's `←` and
   * its swipe right. A run that no longer exists cannot be the
   * selection, and leaving `?run=` on a deleted id would point the
   * detail pane at a 404; `?global=` is inert beside `?run=` and goes
   * too, so leaving the detail always lands on the list and never on a
   * global screen a stale index would open (D218 (3)).
   */
  onClearRun?: (() => void) | undefined
  /**
   * The narrow global screen: `?global=` to this index, or away.
   *
   * `0` opens it on its first pane — a swipe right on the list, or the
   * footer button while the screen is down; a larger index is `◀ ▶`, a
   * dot or a jump key moving inside it; and `undefined` is a swipe left
   * on the screen, the bar's `←`, the footer button while it is up, or
   * `esc` (21 §Narrow layout, D216, D218). Nothing else in the search
   * is touched: `?pane=` is the operator's attention and outlives the
   * visit as it outlives a selection change (10 §Panes). Leaving the
   * detail for the list is `onClearRun`'s, which clears `?global=` too.
   */
  onShowGlobal?: ((index: number | undefined) => void) | undefined
}) {
  const runs = useRunListModel()
  useAttention()
  // Which layout this is. The one thing the CSS cannot say for us: the
  // two regions are two subtrees, and below the breakpoint exactly one
  // of them is mounted (D194).
  const narrow = useIsNarrow()
  // The narrow global screen: beside the list and never over a run, so
  // `?global=` is read only while `?run=` is unset and is inert beside
  // it (D218). At `md` and above the parameter is inert either way —
  // kept, not cleared, as `listCollapsed` is below (D194) — because the
  // detail is the global panes there whenever nothing is selected, and
  // a phone's link opened on a desktop should show what it names.
  const showingGlobal =
    narrow && search.run === undefined && search.global !== undefined
  const showGlobal = onShowGlobal ?? NOTHING
  // One pane model, keyed off the screen, not two: what the middle shows
  // is what the keyboard cycles, what the palette's `append log` looks
  // the log pane up in, and what `Detail` draws, and on the global
  // screen all three are the global cycle — `search.run` is unset
  // there by definition (D218 (1)), so the model needs no second
  // argument to say so. `logPane` and `agentPane` come out `-1` there,
  // so `append log` asks for nothing — which is already what it does
  // with no log pane.
  const panes = usePanes(
    search.run,
    showingGlobal
      ? { index: search.global, onChange: showGlobal }
      : { index: search.pane, onChange: onSelectPane },
  )
  const queryClient = useQueryClient()
  const toggleListCollapsed = usePrefs((state) => state.toggleListCollapsed)
  const listCollapsed = usePrefs((state) => state.listCollapsed)
  const setFontSize = usePrefs((state) => state.setFontSize)
  const focusLogComposer = useUi((state) => state.focusLogComposer)
  const focusedRun = useUi((state) => state.focusedRun)
  const focusRun = useUi((state) => state.focusRun)
  const blurRun = useUi((state) => state.blurRun)

  // Whether a run is held *for this render*: `⏎` picked one up, it is
  // still the selection, its row is still in the filtered list, the
  // viewport is still wide enough for that list to be on screen, and
  // `b` has not collapsed it to the rail — `Splitter` does not mount
  // `RunList` at all when it is collapsed, so a held run would be as
  // invisible there as it is below the breakpoint (D204 (2)). Derived
  // rather than trusted, so the frame between a filter keystroke and
  // the effect below is never drawn with a mode the operator cannot
  // see.
  const runFocused =
    focusedRun !== null &&
    focusedRun === search.run &&
    !narrow &&
    !listCollapsed &&
    runs.rows.some((row) => row.id === focusedRun)

  // ...and the housekeeping that follows it, so a stale id cannot spring
  // back the next time that run is selected.
  useEffect(() => {
    if (focusedRun !== null && !runFocused) blurRun()
  }, [focusedRun, runFocused, blurRun])

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
  // The run a plugin's action is scoped to: the selection, which the
  // global screen never has, as the desktop's global view has none
  // (`panes/actions.ts`, ownership).
  const pluginScopeRun = search.run

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
    // On the narrow global screen the plugin rows are the global view's
    // — every workflow's, resolved against no run — which is the
    // catalogue the desktop's global view has, and the one that lists a
    // plugin's global action beside its global pane (D216). Nothing is
    // selected there, so the run operations above are disabled as they
    // are on the list.
    pluginPaletteActions(
      actionsOf(manifest, { runId: pluginScopeRun, workflow: selected?.workflow }),
      { runId: pluginScopeRun, taskId: search.task },
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
    runFocused,
    // `⏎ focus run`: pick the selected run up, or put the held one
    // down. There is nothing to pick up with no run selected, and no
    // list to move it in below the breakpoint or behind the collapsed
    // rail (D204 (2)) — where `inList()` still answers `true` for the
    // body, so the guard has to be here rather than in the keymap.
    toggleRunFocus: () => {
      if (narrow || listCollapsed || search.run === undefined) return
      if (runFocused) blurRun()
      else focusRun(search.run)
    },
    // `↑`/`↓`/`j`/`k`, while one is held: one swap per press, against
    // the true dispatch neighbour, through the endpoint the palette's
    // two keyless rows already call (`overlays/runOps.ts`, D204 (4)).
    moveRun: (delta) => {
      if (!runFocused || search.run === undefined) return
      runOps.reorder(search.run, delta < 0 ? 'up' : 'down')
    },
    openPalette: onOpenPalette,
    // `esc close`: the overlay first, because it is the nearer thing —
    // and while one is up the arrows are suppressed anyway — then a held
    // run, then the selection itself. Nearest outwards, one rung per
    // keystroke, so `esc` never skips a step the operator can see.
    //
    // The last rung is what makes the `global` panes reachable again: a
    // run stays selected until something clears `?run=`, and until now
    // the only things that did were the delete confirm and the narrow
    // back control — so above the breakpoint, selecting a run was a dead
    // end and the crontab and drop-box panes could not be got back to
    // (D209). The guard matters: a navigation that rewrote the same
    // search would be one history entry per keystroke.
    //
    // The narrow global screen is a rung between the overlay and the
    // held run (D216): a held run is never narrow and the screen is
    // never over a selection (D218), so nothing past the rung is ever
    // reached from it, and it sits where it reads right — one step
    // outwards from the screen the operator is on. Below the breakpoint
    // every press after the overlay is one screen back to the list:
    // global → list, detail → list (D218 (5)).
    close: () => {
      if (search.overlay !== undefined) {
        onCloseOverlay?.()
        return
      }
      if (showingGlobal) {
        showGlobal(undefined)
        return
      }
      if (runFocused) {
        blurRun()
        return
      }
      if (search.run !== undefined) onClearRun?.()
    },
  })

  // The stacked middle of 21 §Narrow layout, one of three screens
  // around the list: `?run=` set is the detail, `?global=` set with no
  // run is the global screen, and neither is the list. At `md` and
  // above there is no stack — the splitter draws both. Read once,
  // here, because the swipe handler below decides on it too.
  const stacked = narrow
    ? showingGlobal
      ? 'global'
      : search.run === undefined
        ? 'list'
        : 'detail'
    : undefined

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
        stacked={stacked}
        // The three screens fan around the list — global | list |
        // detail — and a swipe is one screen along that row, the way
        // the finger moves: right on the list reaches the global
        // screen, on its first pane; left on the global screen puts it
        // away, back to the list; right on the detail is the bar's `←`
        // — the same `onClearRun` write. The detail is never swiped to,
        // so left on the list is nothing, and so are right on the
        // global screen and left on the detail, the row's two ends. A
        // dropped direction is read all the same — the listener is the
        // stacked middle's and stays attached (D218 (2)) — and dropping
        // it is what keeps a swipe from spending a history entry
        // rewriting the same search, the guard 10 §Keyboard gives
        // `esc`.
        onSwipe={(direction) => {
          if (stacked === 'list') {
            if (direction === 'right') showGlobal(0)
          } else if (stacked === 'global') {
            if (direction === 'left') showGlobal(undefined)
          } else if (direction === 'right') {
            onClearRun?.()
          }
        }}
        list={
          <RunList
            model={runs}
            selected={search.run}
            focusedRun={runFocused ? search.run : undefined}
            onSelect={onSelectRun}
          />
        }
        detail={
          <Detail
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
            // The back control: it clears `?run=` through the same
            // write the delete confirm uses, so "back to the list" and
            // "nothing is selected" are one state. Drawn at every width
            // since D209 — below the breakpoint it is 21 §Narrow
            // layout's back arrow, above it, it is the only pointer
            // route to the `global` panes.
            onBack={onClearRun}
            // The global screen's own way back: `?global=` away, and
            // the list — the one thing beside the screen — is what
            // shows (D218).
            leave={
              showingGlobal
                ? () => {
                    showGlobal(undefined)
                  }
                : undefined
            }
          />
        }
      />

      {/* `global` only when narrow: `App` is one of D201 (2)'s three
          `useIsNarrow()` components already, so the width is decided
          here and the footer stays a `max-md:` class away from knowing.
          Above the breakpoint the button is not in the document at all.
          Nor is it on the detail: the button is the discoverable twin
          of the swipe on the screen it is drawn on, and the detail has
          no swipe to the global panes — 21 §Touch operation's rule cuts
          both ways, a gesture is never the only route and a screen with
          no gesture needs no button for it (D218 (4)). So it is drawn
          on the list and the global screen, the two the swipe joins. */}
      <Footer
        onOpenPalette={onOpenPalette}
        global={
          narrow && search.run === undefined
            ? {
                pressed: showingGlobal,
                onToggle: () => {
                  showGlobal(showingGlobal ? undefined : 0)
                },
              }
            : undefined
        }
      />

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
        runId={pluginScopeRun}
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

/**
 * Which panes exist for the current selection, in what order, and where
 * the operator is in them (`docs/v1/10-frontend.md` §Panes).
 *
 * Nothing here has a list of panes. The builtins are declared through
 * the plugin API like anything else (09 §Builtins are plugins) and the
 * manifest lists them first, so "overview, log, agent, requests, graph,
 * then the workflow's own" is the *server's* order and this file only
 * filters it by scope:
 *
 * - a run is selected → the builtin run panes and the run's own
 *   workflow's, because scope follows ownership (09 §Context and
 *   scopes): a workflow's panels show on its runs and on no others;
 * - a `node`-slot panel joins them only while `GET /api/runs/{id}/graph`
 *   reports that node `live`. Liveness is computed server-side and
 *   travels on the graph, so the manifest stays static and the pane
 *   count moves with the run (09 §Slots);
 * - no run is selected → the `global` panes, of every workflow there is,
 *   which is the requests pane's inbox twin and whatever a plugin added
 *   beside it.
 *
 * The index is the operator's attention rather than the run's: it lives
 * in `?pane=`, it survives a change of selection, and it is **clamped**
 * to the pane count when it is read. Clamping rather than rewriting is
 * what makes it survive: a run with three panes must not truncate the
 * index that a run with eight was showing pane six of, or every step
 * through a filtered list would drag the operator back to the start.
 *
 * `next`, `prev` and `jump` are exposed here and bound to `←`, `→` and
 * `1`–`9` in T067. They are actions rather than key handlers precisely
 * so that the pane dots, the bar's arrows and the keyboard all move one
 * piece of state.
 */
import { useMemo } from 'react'

import { getGraphApiRunsRunIdGraphGetOptions } from '../api/gen/@tanstack/react-query.gen'
import type { PanelOut, PluginManifestEntry, RunSummary } from '../api/gen/types.gen'
import { useRuns } from '../components/RunList'
import { useQuery } from '@tanstack/react-query'
import { BUILTIN_WORKFLOW, useManifest } from './manifest'

/** The highest pane a number key reaches: `1`–`9` (10 §Keyboard). */
export const JUMP_KEYS = 9

/** One pane of the cycle: a manifest panel, with where it came from. */
export type Pane = {
  /** `<workflow>:<name>`, unique across the manifest. */
  id: string
  /** The workflow that declared it, `_builtin` for the core's own. */
  workflow: string
  /** The panel's name, which is what the bar and the dots label it. */
  name: string
  /** Whether it is one of the core's own panes (09 §Builtins). */
  builtin: boolean
  /** The manifest entry itself: kind, source, element, `refresh_on`. */
  panel: PanelOut
}

/** What the pane host is looking at: a run, or nothing. */
export type PaneScope = {
  /** The selected run's id, or `undefined` for the global panes. */
  runId: string | undefined
  /** The selected run's workflow, once `GET /api/runs` has said. */
  workflow: string | undefined
}

/** Where the index comes from and where a change to it goes. */
export type PaneCursor = {
  /** `?pane=`, before clamping. */
  index: number | undefined
  /** Write a new index; the route puts it back in the URL. */
  onChange: (index: number) => void
}

export type PaneModel = {
  /** The cycle, in the manifest's order. */
  panes: Pane[]
  /** The selected run's id, straight from `?run=`. */
  runId: string | undefined
  /** The index in range, which is `?pane=` clamped to the count. */
  index: number
  /** The pane at {@link PaneModel.index}, absent when there are none. */
  current: Pane | undefined
  /** `◀ OVERVIEW (1/7) ▶`'s middle, or `—` with nothing to cycle. */
  label: string
  /** The selected run, once the run list has answered. */
  run: RunSummary | undefined
  /** Whether the manifest is still outstanding. */
  isPending: boolean
  /** `←`: the previous pane, wrapping. */
  prev: () => void
  /** `→`: the next pane, wrapping. */
  next: () => void
  /** `1`–`9` and the dots: go to a pane, if there is one there. */
  jump: (index: number) => void
}

/** The label a pane carries in the bar and on its dot's tooltip. */
export function paneLabel(panes: readonly Pane[], index: number): string {
  const pane = panes[index]
  if (pane === undefined) return '—'
  return `${pane.name.toUpperCase()} (${String(index + 1)}/${String(panes.length)})`
}

/**
 * Whether `panel` is a pane of this scope.
 *
 * `placement` decides pane from card before anything else: a
 * `placement="card"` panel is appended to the overview (T063a) and is
 * never a pane of its own, whatever its slot.
 */
function isPaneOf(
  panel: PanelOut,
  hasRun: boolean,
  liveNodes: ReadonlySet<string>,
): boolean {
  if (panel.placement !== 'pane') return false
  if (!hasRun) return panel.slot === 'global'
  if (panel.slot === 'run') return true
  if (panel.slot !== 'node') return false
  return panel.node != null && liveNodes.has(panel.node)
}

/**
 * The cycle, from the manifest and the scope: pure, so the order and the
 * rules can be tested without a server.
 *
 * Entries are taken in the order the manifest gives them — builtins
 * first, then the registered workflows in registration order (09
 * §Mounting) — and this function reorders nothing. With a run selected
 * it keeps the builtin entry and the run's own workflow's; with none it
 * keeps every entry, because a `global` pane belongs to no run and
 * therefore to no owner.
 *
 * A run whose workflow is not known yet — the run list has not answered,
 * or the id in `?run=` names a run that is gone — is still a run: its
 * builtin panes show, and its workflow's join them when the list says
 * which workflow that is.
 */
export function panesOf(
  manifest: readonly PluginManifestEntry[],
  scope: PaneScope,
  liveNodes: ReadonlySet<string>,
): Pane[] {
  const hasRun = scope.runId !== undefined
  const panes: Pane[] = []

  for (const entry of manifest) {
    const builtin = entry.workflow === BUILTIN_WORKFLOW
    if (hasRun && !builtin && entry.workflow !== scope.workflow) continue

    for (const panel of entry.panels ?? []) {
      if (!isPaneOf(panel, hasRun, liveNodes)) continue
      panes.push({
        id: `${entry.workflow}:${panel.name}`,
        workflow: entry.workflow,
        name: panel.name,
        builtin,
        panel,
      })
    }
  }

  return panes
}

/** Whether any panel in scope follows a node, and so needs the graph. */
function needsGraph(
  manifest: readonly PluginManifestEntry[],
  scope: PaneScope,
): boolean {
  return manifest.some(
    (entry) =>
      (entry.workflow === BUILTIN_WORKFLOW || entry.workflow === scope.workflow) &&
      (entry.panels ?? []).some(
        (panel) => panel.slot === 'node' && panel.placement === 'pane',
      ),
  )
}

/**
 * The run's live nodes, or nothing when no panel in scope follows one.
 *
 * The graph is fetched only where liveness decides a pane: the builtins
 * declare no `node` panel, so the common case makes no request at all
 * and the graph pane (T063e) fetches it for itself when it is drawn.
 */
function useLiveNodes(
  runId: string | undefined,
  wanted: boolean,
): ReadonlySet<string> {
  const { queryFn, ...options } = getGraphApiRunsRunIdGraphGetOptions({
    path: { run_id: runId ?? '' },
  })
  const { data } = useQuery({
    ...options,
    queryFn: queryFn!,
    enabled: wanted && runId !== undefined,
  })

  return useMemo(
    () => new Set((data?.nodes ?? []).filter((node) => node.live).map((n) => n.name)),
    [data],
  )
}

/**
 * The pane host: the cycle for `runId`, and the index rules over it.
 *
 * The selected run's workflow comes from `GET /api/runs`, which the app
 * has already read for the run list — the list is returned whole (08
 * §Conventions), so this costs no request and the pane cycle cannot
 * disagree with the row the operator clicked.
 */
export function usePanes(runId: string | undefined, cursor: PaneCursor): PaneModel {
  const { manifest, isPending } = useManifest()
  const { data: runs } = useRuns()

  const run = runId === undefined ? undefined : runs?.find((row) => row.id === runId)
  const scope: PaneScope = { runId, workflow: run?.workflow }
  const liveNodes = useLiveNodes(runId, needsGraph(manifest, scope))

  const panes = panesOf(manifest, scope, liveNodes)

  const index =
    panes.length === 0 ? 0 : Math.min(Math.max(cursor.index ?? 0, 0), panes.length - 1)

  return {
    panes,
    runId,
    index,
    current: panes[index],
    label: paneLabel(panes, index),
    run,
    isPending,
    prev: () => {
      if (panes.length > 0) cursor.onChange((index + panes.length - 1) % panes.length)
    },
    next: () => {
      if (panes.length > 0) cursor.onChange((index + 1) % panes.length)
    },
    jump: (to: number) => {
      if (to >= 0 && to < panes.length) cursor.onChange(to)
    },
  }
}

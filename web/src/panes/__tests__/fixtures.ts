/**
 * The manifest fixtures the pane tests share.
 *
 * They are a manifest as `GET /api/plugins` answers it (09 §Wire
 * contract): the six builtin panels in the order 09 §Builtins are
 * plugins tables them, and two workflows whose panels cover every case
 * the cycle has a rule for — a run pane, a card, a node pane, a global
 * pane, and a second workflow to exclude by ownership.
 */
import type { GraphOut, PanelOut, PluginManifestEntry } from '../../api/gen/types.gen'

/** A panel with the manifest's defaults filled in. */
export function panel(over: Partial<PanelOut> & { name: string }): PanelOut {
  return {
    slot: 'run',
    scope: 'run',
    placement: 'pane',
    kind: 'custom',
    ...over,
  }
}

/**
 * The six builtin panels, in the order 09 §Builtins are plugins tables
 * them: overview, log, agent, requests (plus its global inbox), graph.
 */
export const BUILTIN_ENTRY: PluginManifestEntry = {
  workflow: '_builtin',
  panels: [
    panel({
      name: 'overview',
      kind: 'dashboard',
      source: '/api/plugins/_builtin/overview',
      refresh_on: ['run.*', 'task.*', 'agent.stats'],
    }),
    panel({
      name: 'log',
      kind: 'log',
      source: '/api/plugins/_builtin/log',
      refresh_on: ['log.appended', 'task.*'],
    }),
    panel({ name: 'agent', kind: 'custom', element: 'ath-agent-stream' }),
    panel({ name: 'requests', kind: 'custom', element: 'ath-requests' }),
    panel({
      name: 'inbox',
      slot: 'global',
      scope: 'global',
      kind: 'custom',
      element: 'ath-requests',
    }),
    panel({ name: 'graph', kind: 'custom', element: 'ath-run-graph' }),
  ],
}

/** A workflow with two run panes, a card, a node pane and a global one. */
export const GAMEDEV_ENTRY: PluginManifestEntry = {
  workflow: 'gamedev',
  panels: [
    panel({
      name: 'words',
      kind: 'table',
      source: '/api/plugins/gamedev/words',
      refresh_on: ['log.appended'],
    }),
    panel({
      name: 'sessions',
      kind: 'chart',
      source: '/api/plugins/gamedev/sessions',
    }),
    panel({
      name: 'budget',
      placement: 'card',
      kind: 'kv',
      source: '/api/plugins/gamedev/budget',
    }),
    panel({
      name: 'playfield',
      slot: 'node',
      scope: 'node',
      node: 'qa',
      kind: 'custom',
      element: 'gd-playfield',
    }),
    panel({
      name: 'leaderboard',
      slot: 'global',
      scope: 'global',
      kind: 'markdown',
      source: '/api/plugins/gamedev/leaderboard',
    }),
  ],
}

/** Another workflow, so ownership has something to exclude. */
export const OTHER_ENTRY: PluginManifestEntry = {
  workflow: 'feature_build',
  panels: [
    panel({ name: 'diff', kind: 'markdown', source: '/api/plugins/feature_build/diff' }),
  ],
}

export const MANIFEST: PluginManifestEntry[] = [
  BUILTIN_ENTRY,
  GAMEDEV_ENTRY,
  OTHER_ENTRY,
]

/** A graph in which `qa` is live and `engineering` is not. */
export function graph(live: readonly string[]): GraphOut {
  return {
    edges: [],
    nodes: ['engineering', 'qa'].map((name, index) => ({
      name,
      generation: index,
      attempts: 1,
      join: false,
      state: 'idle',
      live: live.includes(name),
    })),
  }
}

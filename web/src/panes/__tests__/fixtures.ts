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

/**
 * One sample per data kind, in the shape 09 §Panel kinds gives it.
 *
 * The values are the design mock's own `PLUGINS.gamedev.playtest`
 * (`docs/v1/design/Athanore.dc.html`) — the pane 10 §Panes item 6
 * describes — so the renderers are tested against the data the design
 * was drawn for rather than against something invented here.
 */
export const SAMPLES = {
  /** `markdown`: `string`. */
  markdown: [
    '# playtest',
    '',
    'Runs the build headless and reports **frame timing** plus crash traces.',
    '',
    '| session | outcome |',
    '| --- | --- |',
    '| s-01 | clear |',
    '| s-03 | crash |',
    '',
    '```python',
    'assert fps > 55',
    '```',
  ].join('\n'),

  /** `kv`: `dict`. */
  kv: {
    IMAGE: 'py312',
    UPTIME: '14m',
    MOUNTS: 3,
    CRASHES: null,
  },

  /** `table`: `{columns: [{key, label, kind?}], rows: [{…}]}`. */
  table: {
    columns: [
      { key: 'session', label: 'SESSION' },
      { key: 'outcome', label: 'OUTCOME' },
      { key: 'fps', label: 'FPS', kind: 'number' },
    ],
    rows: [
      { session: 's-01', outcome: 'clear', fps: 61 },
      { session: 's-02', outcome: 'clear', fps: 59.8 },
      { session: 's-03', outcome: 'crash', fps: null },
      { session: 's-04', outcome: 'clear', fps: 57.2 },
    ],
  },

  /** `log`: `[{ts, text, level?}]`, with the `source` the builtin adds. */
  log: [
    {
      ts: '2026-09-08T09:00:01Z',
      source: 'engineering/engine',
      text: 'engineering queued',
      level: 'dim',
    },
    {
      ts: '2026-09-08T09:00:02Z',
      source: 'engineering/agent',
      text: 'wrote the pane host',
      level: 'default',
    },
    {
      ts: '2026-09-08T09:00:03Z',
      source: 'engineering/agent',
      text: '[stats] 12480 tokens',
      level: 'accent',
    },
    {
      ts: '2026-09-08T09:00:04Z',
      source: 'engineering/engine',
      text: 'engineering → qa',
      level: 'dim',
    },
  ],

  /** `chart`: `{series: [{name, points: [[x, y]]}], kind: line|bar}`. */
  chart: {
    series: [
      {
        name: 'fps',
        points: [
          [1, 61],
          [2, 59.8],
          [3, 57.2],
          [4, 58.9],
        ],
      },
    ],
    kind: 'line',
  },

  /** `dashboard`: `{note?, metrics: [{label, value}], table?}`. */
  dashboard: {
    note: 'Runs the build headless and reports frame timing plus crash traces.',
    metrics: [
      { label: 'SESSIONS', value: 12 },
      { label: 'AVG FPS', value: 58.4 },
      { label: 'CRASHES', value: 1 },
    ],
    table: {
      columns: [
        { key: 'session', label: 'SESSION' },
        { key: 'outcome', label: 'OUTCOME' },
        { key: 'fps', label: 'FPS', kind: 'number' },
      ],
      rows: [
        { session: 's-01', outcome: 'clear', fps: 61 },
        { session: 's-03', outcome: 'crash', fps: null },
      ],
    },
  },
} as const

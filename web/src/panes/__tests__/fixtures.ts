/**
 * The manifest fixtures the pane tests share.
 *
 * They are a manifest as `GET /api/plugins` answers it (09 §Wire
 * contract): the six builtin panels in the order 09 §Builtins are
 * plugins tables them, and two workflows whose panels cover every case
 * the cycle has a rule for — a run pane, a card, a node pane, a global
 * pane, and a second workflow to exclude by ownership.
 *
 * Below them, one sample per panel kind (`SAMPLES`), the overview pane's
 * own two sides — what `GET /api/plugins/_builtin/overview` answers
 * with, and the `RunDetail` the pane reads beside it — and the event
 * log's, which is its route's merged list and the run it belongs to,
 * the agent pane's, which is one attempt's transcript and the run
 * detail the pane picks that attempt out of, the requests pane's, which
 * is one run's whole human-in-the-loop history, and the graph pane's
 * three shapes — linear with a loop-back, a fan-out that never closes,
 * and the same fan-out closed by a join.
 */
import type {
  GraphNode,
  GraphOut,
  PanelOut,
  PluginManifestEntry,
  RequestView,
  RunDetail,
  RunOutput,
  RunStatus,
  RunSummary,
  StreamChunk,
  StreamOut,
  TaskView,
} from '../../api/gen/types.gen'
import type { TableColumn } from '../kinds'

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

/* -------------------------------------------------------------------- */
/* The overview pane                                                     */
/* -------------------------------------------------------------------- */

/** The run every overview fixture below is about. */
export const OVERVIEW_RUN = '01JD5XOVERVIEW0000000000'

/**
 * The NODES columns `athanore/plugins/builtin/overview.py` declares, in
 * the order 10 §Panes draws them.
 */
export const NODE_COLUMNS: TableColumn[] = [
  { key: 'node', label: 'NODE', kind: 'text' },
  { key: 'attempts', label: 'ATT', kind: 'number' },
  { key: 'status', label: 'STATUS', kind: 'status' },
  { key: 'tokens', label: 'TOKENS', kind: 'number' },
  { key: 'duration_s', label: 'DUR', kind: 'duration' },
]

/**
 * `GET /api/plugins/_builtin/overview` for a run mid-flight.
 *
 * The numbers are the mock's own first run (`docs/v1/design/
 * Athanore.dc.html`, `a4c81f20b91e`) in the shape the route sends them:
 * raw counts and seconds, `meta` beside the three `dashboard` keys, and
 * **nothing zero-filled** — `review` has entered no agent, so its row
 * carries neither `tokens` nor `duration_s`.
 */
export const OVERVIEW_SOURCE = {
  note: 'Port the TUI pane cycle to the web app.',
  metrics: [
    { label: 'TOKENS', value: 612884 },
    { label: 'COST', value: 0.2914 },
    { label: 'DURATION', value: 246.4 },
    { label: 'POSITION', value: '1 of 34' },
  ],
  table: {
    columns: NODE_COLUMNS,
    rows: [
      { node: 'prompt', attempts: 1, status: 'done', tokens: 18204, duration_s: 9.2 },
      { node: 'product', attempts: 1, status: 'done', tokens: 61933, duration_s: 58 },
      {
        node: 'architecture',
        attempts: 1,
        status: 'done',
        tokens: 119447,
        duration_s: 74,
      },
      {
        node: 'engineering',
        attempts: 2,
        status: 'in_progress',
        tokens: 413300,
        duration_s: 105,
      },
      { node: 'review', attempts: 1, status: 'ready' },
    ],
  },
  meta: {
    RUN: OVERVIEW_RUN,
    WORKFLOW: 'feature_build',
    TITLE: 'Rebuild run detail as a web pane set',
    STATUS: 'running · engineering',
    AGE: 246.4,
    SESSION: '01a02310f5c74b1e9a',
    AGENTS: 4,
    DESCRIPTION: 'Port the TUI pane cycle to the web app.',
  },
}

/**
 * The same route for a run no agent has touched: a queued run, one
 * minute old.
 *
 * TOKENS, COST, SESSION and AGENTS are **absent** rather than zero — the
 * route omits what nothing measured (01 §Real data only) — which is the
 * case this pane must render without inventing a `0` for any of them.
 */
export const IDLE_OVERVIEW_SOURCE = {
  metrics: [
    { label: 'DURATION', value: 61.5 },
    { label: 'POSITION', value: '3 of 34' },
  ],
  table: { columns: NODE_COLUMNS, rows: [{ node: 'prompt', attempts: 1, status: 'ready' }] },
  meta: {
    RUN: OVERVIEW_RUN,
    WORKFLOW: 'feature_build',
    TITLE: 'append log',
    STATUS: 'queued',
    AGE: 61.5,
  },
}

/** One attempt of {@link runDetail}, with the fields the pane reads. */
function attempt(id: number, node: string, over: Partial<TaskView> = {}): TaskView {
  return {
    id,
    run_id: OVERVIEW_RUN,
    node,
    attempt: 1,
    status: 'done',
    priority: 0,
    explicit: false,
    terminal: false,
    created: '2026-09-08T08:56:00Z',
    ...over,
  }
}

/**
 * `GET /api/runs/{id}` for {@link OVERVIEW_SOURCE}'s run.
 *
 * The attempts are the ones behind its NODES rows, oldest first (08
 * §Runs), so `engineering` has the two the ATT column counts and the
 * drawer opens on the later of them.
 */
export function runDetail(over: Partial<RunDetail> = {}): RunDetail {
  return {
    id: OVERVIEW_RUN,
    workflow: 'feature_build',
    title: 'Rebuild run detail as a web pane set',
    description: 'Port the TUI pane cycle to the web app.',
    status: 'running',
    position: 1,
    current_nodes: ['engineering'],
    created: '2026-09-08T08:56:00Z',
    updated: '2026-09-08T09:00:06Z',
    outputs: [],
    tasks: [
      attempt(401, 'prompt'),
      attempt(402, 'product'),
      attempt(403, 'architecture'),
      attempt(404, 'engineering', { status: 'failed', attempt: 1 }),
      attempt(405, 'engineering', { status: 'in_progress', attempt: 2 }),
      attempt(406, 'review', { status: 'ready' }),
    ],
    ...over,
  }
}

/** Two branches that terminated independently (04 §Routing edge cases). */
export const FANNED_OUT: RunOutput[] = [
  {
    task_id: 501,
    node: 'render',
    branch: [{ index: 0, key: 'alpha' }],
    value: { frames: 240, crashes: 0 },
  },
  {
    task_id: 502,
    node: 'render',
    branch: [{ index: 1, key: 'beta' }],
    value: 'beta ran clean',
  },
]

/* -------------------------------------------------------------------- */
/* The event log pane                                                    */
/* -------------------------------------------------------------------- */

/** The run the event-log fixtures below are about. */
export const LOG_RUN = '01JD5XEVENTLOG0000000000'

/**
 * `GET /api/plugins/_builtin/log` for a run mid-flight.
 *
 * One list from two sources, as `athanore/plugins/builtin/log.py` sends
 * it: work-log entries (`node/author`, the tone of what wrote them) and
 * lifecycle events (`node/engine`, or bare `engine` where the payload
 * named no node, each one sentence). Every field this pane reads is
 * here — the three tones of 10 §Panes, an agent entry written in
 * markdown, and the `node` the `?node=` filter narrows by.
 *
 * The `run.created` line is **last in the array and first in time**. The
 * route sends the list merged, so nothing in the SPA depends on that
 * being out of order — which is exactly why the fixture is: a pane that
 * drew rows in the order they arrived would draw this one in the wrong
 * place.
 */
export const EVENT_LOG = [
  {
    ts: '2026-09-08T09:00:01Z',
    source: 'engineering/engine',
    node: 'engineering',
    text: 'architecture \u2192 engineering',
    level: 'dim',
  },
  {
    ts: '2026-09-08T09:00:02Z',
    source: 'engineering/agent',
    node: 'engineering',
    text: '## report\n\nwrote the **pane host**',
    level: 'default',
  },
  {
    ts: '2026-09-08T09:00:03Z',
    source: 'engineering/engine',
    node: 'engineering',
    text: '[stats] 12,480 tokens \u00b7 $0.03 \u00b7 41.2s',
    level: 'accent',
  },
  {
    ts: '2026-09-08T09:00:04Z',
    source: 'qa/user',
    node: 'qa',
    text: 'looks *right* to me',
    level: 'default',
  },
  {
    ts: '2026-09-08T09:00:00Z',
    source: 'engine',
    text: 'run created in feature_build at position 1',
    level: 'dim',
  },
]

/** The run {@link EVENT_LOG} belongs to, in whatever status. */
export function logRun(status: RunStatus = 'running'): RunSummary {
  return {
    id: LOG_RUN,
    workflow: 'feature_build',
    title: 'Rebuild run detail as a web pane set',
    status,
    position: 1,
    current_nodes: status === 'running' ? ['engineering'] : [],
    created: '2026-09-08T08:56:00Z',
    updated: '2026-09-08T09:00:06Z',
  }
}

/* -------------------------------------------------------------------- */
/* The agent pane                                                        */
/* -------------------------------------------------------------------- */

/** The run the transcript fixtures below are about. */
export const STREAM_RUN = '01JD5XAGENTSTREAM0000000'

/** The attempt whose transcript {@link TRANSCRIPT} is. */
export const STREAM_TASK = 405

/**
 * `GET /api/tasks/{id}/stream` for an attempt mid-turn.
 *
 * One chunk of every kind of `ChunkKind` (03 §StreamChunk), in the order
 * the façade writes them (`athanore/agents/acp.py`): a notice, thinking,
 * a tool call and what it returned, then the answer — with the answer
 * arriving in the two fragments an `agent_message_chunk` really comes
 * in, so the pane is tested against a stream and not against a
 * transcript somebody tidied up first.
 */
export const TRANSCRIPT: StreamChunk[] = [
  {
    seq: 1,
    kind: 'notice',
    text:
      "thought_level could not be set to 'max': unknown option. " +
      'The agent is answering on its own default.',
    created: '2026-09-08T09:00:01Z',
  },
  {
    seq: 2,
    kind: 'thought',
    text: 'The pane cycle is an index; the keymap should drive the same reducer.',
    created: '2026-09-08T09:00:02Z',
  },
  {
    seq: 3,
    kind: 'tool_call',
    text: 'read · artificer/tui.py',
    created: '2026-09-08T09:00:03Z',
  },
  {
    seq: 4,
    kind: 'tool_result',
    text: 'PANES = ("overview", "log", "agent", "graph", "messages")',
    created: '2026-09-08T09:00:04Z',
  },
  {
    seq: 5,
    kind: 'text',
    text: 'Tests pass (14 passed). ',
    created: '2026-09-08T09:00:05Z',
  },
  {
    seq: 6,
    kind: 'text',
    text: 'Pane state is now a single index.',
    created: '2026-09-08T09:00:06Z',
  },
]

/** A page of the transcript, as `GET /api/tasks/{id}/stream` sends it. */
export function streamPage(
  chunks: readonly StreamChunk[] = TRANSCRIPT,
  live = true,
): StreamOut {
  return {
    chunks: [...chunks],
    last_seq: chunks.reduce((highest, chunk) => Math.max(highest, chunk.seq), 0),
    live,
  }
}

/**
 * `GET /api/runs/{id}` for {@link TRANSCRIPT}'s run.
 *
 * `engineering` attempt 2 is the one in flight, and the failed attempt
 * before it carries the stats entry the header's `node → model` comes
 * from — so the fixture covers both halves of the focus rule and the
 * field that is omitted until an agent has reported one.
 */
export function streamRun(over: Partial<RunDetail> = {}): RunDetail {
  return {
    id: STREAM_RUN,
    workflow: 'feature_build',
    title: 'Rebuild run detail as a web pane set',
    status: 'running',
    position: 1,
    current_nodes: ['engineering'],
    created: '2026-09-08T08:56:00Z',
    updated: '2026-09-08T09:00:06Z',
    outputs: [],
    tasks: [
      { ...attempt(403, 'architecture'), run_id: STREAM_RUN },
      {
        ...attempt(404, 'engineering', {
          status: 'failed',
          attempt: 1,
          stats: { model: 'claude-opus-5', total_tokens: 41200 },
        }),
        run_id: STREAM_RUN,
      },
      {
        ...attempt(STREAM_TASK, 'engineering', {
          status: 'in_progress',
          attempt: 2,
          stats: { model: 'claude-opus-5' },
        }),
        run_id: STREAM_RUN,
      },
      { ...attempt(406, 'review', { status: 'ready' }), run_id: STREAM_RUN },
    ],
    ...over,
  }
}

/* -------------------------------------------------------------------- */
/* The requests pane                                                     */
/* -------------------------------------------------------------------- */

/** The run the request fixtures below are about. */
export const REQUESTS_RUN = '01JD5XREQUESTS0000000000'

/** A request with the fields every view carries filled in. */
export function request(over: Partial<RequestView> & { id: number }): RequestView {
  return {
    run_id: REQUESTS_RUN,
    task_id: 404,
    node: 'engineering',
    prompt: 'may I?',
    mode: 'text',
    source: 'node',
    kind: 'question',
    pending: false,
    stale: false,
    created: '2026-09-08T09:00:00Z',
    age: 60,
    ...over,
  }
}

/**
 * `GET /api/runs/{id}/requests` for a run that has asked four things.
 *
 * In the order the route sends them, which is the order they were asked
 * (`athanore/store/repos/requests.py`): **the two pending ones are third
 * and fourth**, so a pane that drew the list as it arrived would draw
 * them last. One of each state and one of each mode, and the answered
 * permission is the one the clock answered — `permission_timeout_action`
 * records an `engine`-authored answer (06 §Timeouts), which is the case
 * the card's author line exists for.
 */
export const REQUEST_LIST: RequestView[] = [
  request({
    id: 11,
    task_id: 404,
    node: 'engineering',
    source: 'node',
    kind: 'question',
    mode: 'text',
    prompt: 'Which package manager should the scaffold use?',
    answer: 'pnpm, as 02 §Library choices fixes it',
    answered_by: 'user',
    created: '2026-09-08T09:00:01Z',
    age: 305,
  }),
  request({
    id: 12,
    task_id: 404,
    node: 'engineering',
    source: 'agent',
    kind: 'permission',
    mode: 'options',
    prompt: 'permission: write web/src/panes/kinds/Requests.tsx',
    options: [
      { option_id: 'allow_once', name: 'Allow once', kind: 'allow_once' },
      { option_id: 'reject_once', name: 'Reject', kind: 'reject_once' },
    ],
    tool_call: {
      title: 'write web/src/panes/kinds/Requests.tsx',
      kind: 'edit',
      raw_input: '{"path": "web/src/panes/kinds/Requests.tsx", "mode": "create"}',
    },
    answer: 'reject_once',
    answered_by: 'engine',
    created: '2026-09-08T09:00:02Z',
    age: 244,
  }),
  request({
    id: 13,
    task_id: 405,
    node: 'engineering',
    source: 'agent',
    kind: 'permission',
    mode: 'options',
    prompt: 'permission: run the gate',
    options: [
      { option_id: 'allow_once', name: 'Allow once', kind: 'allow_once' },
      { option_id: 'allow_always', name: 'Allow for this session', kind: 'allow_always' },
      { option_id: 'reject_once', name: 'Reject', kind: 'reject_once' },
    ],
    tool_call: {
      title: './scripts/test.sh',
      kind: 'execute',
      raw_input: '{"command": "./scripts/test.sh", "cwd": "/home/agent/athanore"}',
    },
    pending: true,
    created: '2026-09-08T09:00:03Z',
    age: 12,
  }),
  request({
    id: 14,
    task_id: 405,
    node: 'engineering',
    source: 'agent',
    kind: 'elicitation',
    mode: 'form',
    prompt: 'Which branch should the work land on?',
    schema: {
      type: 'object',
      properties: { branch: { type: 'string' } },
      required: ['branch'],
    },
    pending: true,
    created: '2026-09-08T09:00:04Z',
    age: 4,
  }),
]

/** A question whose attempt has ended: in history, no longer answerable. */
export const STALE_REQUEST: RequestView = request({
  id: 15,
  task_id: 403,
  node: 'architecture',
  prompt: 'Should the graph rail draw joins inline?',
  stale: true,
  created: '2026-09-08T08:58:00Z',
  age: 420,
})

/* -------------------------------------------------------------------- */
/* The graph pane                                                        */
/* -------------------------------------------------------------------- */

/** The run the three graph fixtures below are about. */
export const GRAPH_RUN = '01JD5XGRAPHRAIL000000000'

/** A node with the graph route's defaults filled in. */
export function graphNode(
  over: Partial<GraphNode> & { name: string; generation: number },
): GraphNode {
  return {
    join: false,
    state: 'idle',
    live: false,
    attempts: 0,
    branches: [],
    ...over,
  }
}

/**
 * The mock's own pipeline, cut to five nodes and with its two loops:
 * `review → engineering` and `qa → engineering` (the mock's `EDGES`).
 *
 * `engineering` is the node in flight and the node both loops point back
 * at, so this one fixture carries the `attempt n · elapsed` detail, the
 * `●` glyph with its pulse, the `◀` arrow, the rail that spans three
 * rows and the single `loop` label at the middle of it.
 */
export const LINEAR_GRAPH: GraphOut = {
  nodes: [
    graphNode({
      name: 'prompt',
      generation: 0,
      state: 'done',
      live: true,
      attempts: 1,
      last_task_id: 701,
      branches: [{ from_task: null, tasks: [701] }],
    }),
    graphNode({
      name: 'engineering',
      generation: 1,
      state: 'in_progress',
      live: true,
      attempts: 2,
      last_task_id: 703,
      branches: [{ from_task: null, tasks: [702, 703] }],
    }),
    graphNode({
      name: 'review',
      generation: 2,
      state: 'waiting',
      live: true,
      attempts: 1,
      last_task_id: 704,
      branches: [{ from_task: null, tasks: [704] }],
    }),
    graphNode({ name: 'qa', generation: 3 }),
    graphNode({ name: 'git', generation: 4 }),
  ],
  edges: [
    { from: 'prompt', to: 'engineering', kind: 'forward', traversed: 1 },
    { from: 'engineering', to: 'review', kind: 'forward', traversed: 1 },
    { from: 'review', to: 'qa', kind: 'forward', traversed: 0 },
    { from: 'qa', to: 'git', kind: 'forward', traversed: 0 },
    { from: 'review', to: 'engineering', kind: 'back', traversed: 1 },
    { from: 'qa', to: 'engineering', kind: 'back', traversed: 0 },
  ],
}

/** `GET /api/runs/{id}` for {@link LINEAR_GRAPH}: the attempts behind it. */
export function linearRun(over: Partial<RunDetail> = {}): RunDetail {
  return {
    id: GRAPH_RUN,
    workflow: 'feature_build',
    title: 'Rebuild run detail as a web pane set',
    status: 'running',
    position: 1,
    current_nodes: ['engineering'],
    created: '2026-09-08T08:56:00Z',
    updated: '2026-09-08T09:00:06Z',
    outputs: [],
    tasks: [
      {
        ...attempt(701, 'prompt', {
          started: '2026-09-08T08:56:00Z',
          finished: '2026-09-08T08:56:09Z',
          stats: { total_tokens: 18204 },
        }),
        run_id: GRAPH_RUN,
      },
      {
        ...attempt(702, 'engineering', {
          status: 'failed',
          attempt: 1,
          started: '2026-09-08T08:57:00Z',
          finished: '2026-09-08T08:58:00Z',
        }),
        run_id: GRAPH_RUN,
      },
      {
        ...attempt(703, 'engineering', {
          status: 'in_progress',
          attempt: 2,
          started: '2026-09-08T09:00:00Z',
        }),
        run_id: GRAPH_RUN,
      },
      {
        ...attempt(704, 'review', { status: 'waiting' }),
        run_id: GRAPH_RUN,
      },
    ],
    ...over,
  }
}

/**
 * A fan-out of two branches that never closes: `plan` opened them at
 * task 601 and each branch ran `render` and then `report`.
 *
 * Both branches carry the **same** `from_task`, which is what 08 §Graph
 * semantics says two branches of one fan-out do — so a renderer that
 * grouped by `from_task` alone would draw one sub-list here instead of
 * two.
 */
export const FANOUT_GRAPH: GraphOut = {
  nodes: [
    graphNode({
      name: 'plan',
      generation: 0,
      state: 'done',
      live: true,
      attempts: 1,
      last_task_id: 601,
      branches: [{ from_task: null, tasks: [601] }],
    }),
    graphNode({
      name: 'render',
      generation: 1,
      state: 'done',
      live: true,
      attempts: 2,
      last_task_id: 603,
      branches: [
        { from_task: 601, tasks: [602] },
        { from_task: 601, tasks: [603] },
      ],
    }),
    graphNode({
      name: 'report',
      generation: 2,
      state: 'done',
      live: true,
      attempts: 2,
      last_task_id: 605,
      // **Branch 2's report is first.** The route groups a node's
      // attempts in the order they were enqueued, and branch 2's render
      // finished first, so `report`'s entries are in the opposite order
      // to `render`'s — which is exactly the case a renderer that paired
      // the entries by position would get wrong (08 §Graph semantics).
      branches: [
        { from_task: 601, tasks: [605] },
        { from_task: 601, tasks: [604] },
      ],
    }),
  ],
  edges: [
    { from: 'plan', to: 'render', kind: 'forward', traversed: 2 },
    { from: 'render', to: 'report', kind: 'forward', traversed: 2 },
  ],
}

/**
 * The same fan-out, closed by a join that one of the two branches has
 * reached: `merge` carries `arrivals` and is what the `1 of 2 arrived`
 * detail is read off (08 §Graph semantics).
 */
export const JOINED_GRAPH: GraphOut = {
  nodes: [
    ...FANOUT_GRAPH.nodes,
    graphNode({
      name: 'merge',
      generation: 3,
      join: true,
      arrivals: { arrived: 1, count: 2 },
    }),
  ],
  edges: [
    ...FANOUT_GRAPH.edges,
    { from: 'report', to: 'merge', kind: 'join', traversed: 1 },
  ],
}

/** `GET /api/runs/{id}` for the two fan-out graphs above. */
export function fannedRun(over: Partial<RunDetail> = {}): RunDetail {
  const branch = (index: number) => [
    { fanout: 601, index, count: 2, key: index === 0 ? 'alpha' : 'beta' },
  ]
  return {
    id: GRAPH_RUN,
    workflow: 'gamedev',
    title: 'Render both variants',
    status: 'running',
    position: 2,
    current_nodes: [],
    created: '2026-09-08T08:56:00Z',
    updated: '2026-09-08T09:00:06Z',
    outputs: [],
    tasks: [
      { ...attempt(601, 'plan'), run_id: GRAPH_RUN },
      {
        ...attempt(602, 'render', {
          branch: branch(0),
          started: '2026-09-08T08:57:00Z',
          finished: '2026-09-08T08:57:20Z',
          stats: { total_tokens: 4000 },
        }),
        run_id: GRAPH_RUN,
      },
      {
        ...attempt(603, 'render', {
          branch: branch(1),
          started: '2026-09-08T08:57:00Z',
          finished: '2026-09-08T08:57:40Z',
          stats: { total_tokens: 9000 },
        }),
        run_id: GRAPH_RUN,
      },
      {
        ...attempt(604, 'report', {
          branch: branch(0),
          started: '2026-09-08T08:58:00Z',
          finished: '2026-09-08T08:58:05Z',
        }),
        run_id: GRAPH_RUN,
      },
      {
        ...attempt(605, 'report', {
          branch: branch(1),
          started: '2026-09-08T08:57:41Z',
          finished: '2026-09-08T08:57:44Z',
        }),
        run_id: GRAPH_RUN,
      },
    ],
    ...over,
  }
}

/** `GET /api/workflows/{name}/source`, as the SOURCE line reads it. */
export const WORKFLOW_SOURCE = {
  file: '/srv/athanore/examples/feature_build.py',
  source: 'wf = Workflow("feature_build")\n',
  nodes: { engineering: { line: 12 } },
}

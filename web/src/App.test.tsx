import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import {
  getGraphApiRunsRunIdGraphGetQueryKey,
  getRunApiRunsRunIdGetQueryKey,
  getSourceApiWorkflowsNameSourceGetQueryKey,
  getTaskApiTasksTaskIdGetQueryKey,
  listRunsApiRunsGetQueryKey,
  listWorkflowsApiWorkflowsGetQueryKey,
  manifestApiPluginsGetQueryKey,
} from './api/gen/@tanstack/react-query.gen'
import type {
  GraphOut,
  PluginManifestEntry,
  RunDetail,
  RunSummary,
  TaskDetail,
  WorkflowOut,
} from './api/gen/types.gen'
import type { AppSearch, Overlay } from './routes/search'
import { PALETTE_COMMANDS } from './overlays'
import { KEY_BINDINGS } from './lib/keys'
import { DEFAULT_LIST_WIDTH, usePrefs } from './store/prefs'
import { ALL_WORKFLOWS, useUi } from './store/ui'

const RUNS: RunSummary[] = [
  {
    id: 'aaaa1111bbbb',
    workflow: 'feature_build',
    title: 'rebuild run detail',
    status: 'running',
    position: 1,
    current_nodes: ['engineering'],
    created: '2026-09-08T08:56:00Z',
    updated: '2026-09-08T08:59:00Z',
  },
  {
    id: 'cccc3333dddd',
    workflow: 'gamedev',
    title: 'squirrels vs chipmunks',
    status: 'completed',
    position: 2,
    created: '2026-09-01T08:00:00Z',
    updated: '2026-09-01T09:00:00Z',
  },
]

/** The three builtin panes a pane bar has something to cycle with. */
const MANIFEST: PluginManifestEntry[] = [
  {
    workflow: '_builtin',
    panels: [
      { name: 'overview', slot: 'run', placement: 'pane', scope: 'run', kind: 'custom' },
      { name: 'log', slot: 'run', placement: 'pane', scope: 'run', kind: 'custom' },
      { name: 'agent', slot: 'run', placement: 'pane', scope: 'run', kind: 'custom' },
    ],
  },
]

/** The index of `agent` in that cycle: what `focus stream` jumps to. */
const AGENT_PANE_INDEX = 2

// The library overlay highlights its source with shiki, which is a
// chunk this suite has no reason to load: the overlay draws its lines
// plain until the tokens arrive, and that is the state asserted here.
vi.mock('./lib/highlight', () => ({
  highlight: () => Promise.resolve(null),
  tokenize: () => Promise.resolve(null),
}))

/** The module the one registered workflow is defined in. */
const SOURCE = {
  file: '/srv/workflows/feature_build.py',
  source: '@wf.node(entry=True)\ndef prepare(ctx):\n    pass\n',
  nodes: { prepare: { line: 1 } },
}

/** The selected run, as the edit overlay and the pickers read it. */
const RUN_DETAIL: RunDetail = {
  id: 'aaaa1111bbbb',
  workflow: 'feature_build',
  title: 'rebuild run detail',
  description: 'the detail pane, from the top',
  status: 'running',
  position: 1,
  created: '2026-09-08T08:56:00Z',
  updated: '2026-09-08T08:59:00Z',
  tasks: [
    {
      id: 7,
      run_id: 'aaaa1111bbbb',
      node: 'prepare',
      attempt: 1,
      status: 'failed',
      priority: 0,
      explicit: false,
      terminal: false,
      created: '2026-09-08T08:56:00Z',
    },
  ],
}

/** ...and its graph, which is where the pickers read `join` from. */
const RUN_GRAPH: GraphOut = {
  nodes: [
    {
      name: 'prepare',
      generation: 0,
      join: false,
      live: false,
      attempts: 1,
      state: 'failed',
    },
  ],
  edges: [],
}

/** The attempt `?task=` names, as the task drawer reads it. */
const TASK_DETAIL: TaskDetail = {
  id: 7,
  run_id: 'aaaa1111bbbb',
  node: 'prepare',
  attempt: 1,
  status: 'failed',
  priority: 0,
  explicit: false,
  terminal: false,
  created: '2026-09-08T08:56:00Z',
  error: 'AssertionError: the gate is red',
  lineage: { reason: 'start' },
  submissions: [],
}

/** The registered workflows the New Run overlay's chips are built from. */
const WORKFLOWS: WorkflowOut[] = [
  {
    name: 'feature_build',
    start: 'prepare',
    capacity: 1,
    in_flight: 0,
    nodes: {},
    plugin: { panels: [], actions: [] },
    pool: 'default',
  },
]

/**
 * The shell over a seeded cache.
 *
 * `staleTime` keeps the seeded entries fresh, so nothing here reaches
 * for the network: the fetches behind `GET /api/runs` and
 * `GET /api/plugins` are the generated client's and are exercised where
 * they belong (`api/__tests__`, `panes/__tests__`).
 */
function shell(
  search: AppSearch = {},
  over: {
    runs?: RunSummary[]
    onSelectRun?: (runId: string) => void
    onSelectPane?: (index: number) => void
    onOpenOverlay?: (overlay: Overlay) => void
    onCloseOverlay?: () => void
    onFocusStream?: (taskId: number, pane: number | undefined) => void
    onOpenNode?: (node: string, pane: number | undefined) => void
    onOpenAction?: (action: string) => void
    manifest?: PluginManifestEntry[]
  } = {},
) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { staleTime: 5000, retry: false } },
  })
  queryClient.setQueryData(listRunsApiRunsGetQueryKey(), over.runs ?? RUNS)
  queryClient.setQueryData(manifestApiPluginsGetQueryKey(), over.manifest ?? MANIFEST)
  queryClient.setQueryData(listWorkflowsApiWorkflowsGetQueryKey(), WORKFLOWS)
  queryClient.setQueryData(
    getSourceApiWorkflowsNameSourceGetQueryKey({ path: { name: 'feature_build' } }),
    SOURCE,
  )
  queryClient.setQueryData(
    getRunApiRunsRunIdGetQueryKey({ path: { run_id: 'aaaa1111bbbb' } }),
    RUN_DETAIL,
  )
  queryClient.setQueryData(
    getGraphApiRunsRunIdGraphGetQueryKey({ path: { run_id: 'aaaa1111bbbb' } }),
    RUN_GRAPH,
  )
  queryClient.setQueryData(
    getTaskApiTasksTaskIdGetQueryKey({ path: { task_id: 7 } }),
    TASK_DETAIL,
  )

  const rendered = render(
    <QueryClientProvider client={queryClient}>
      <App
        search={search}
        onSelectRun={over.onSelectRun ?? (() => {})}
        onSelectPane={over.onSelectPane ?? (() => {})}
        onOpenPalette={() => {}}
        {...(over.onOpenOverlay === undefined
          ? {}
          : { onOpenOverlay: over.onOpenOverlay })}
        {...(over.onCloseOverlay === undefined
          ? {}
          : { onCloseOverlay: over.onCloseOverlay })}
        {...(over.onFocusStream === undefined
          ? {}
          : { onFocusStream: over.onFocusStream })}
        {...(over.onOpenNode === undefined ? {} : { onOpenNode: over.onOpenNode })}
        {...(over.onOpenAction === undefined
          ? {}
          : { onOpenAction: over.onOpenAction })}
      />
    </QueryClientProvider>,
  )

  return { ...rendered, queryClient }
}

/** The palette row whose left column reads `name`. */
function command(name: string) {
  return screen.getByRole('option', { name: new RegExp(`^${name}`) })
}

function rows() {
  return within(screen.getByRole('listbox', { name: 'run rows' })).queryAllByRole(
    'option',
  )
}

/**
 * A fresh tab: no client state left over, and a server that answers.
 *
 * The cache is seeded, so nothing here needs the network — except
 * `refresh`, which invalidates every entry this tab holds and so
 * refetches all of them. Answering those keeps a rejected request from
 * surfacing as an unhandled error in whichever test happens to be
 * running when it lands.
 */
function freshTab() {
  vi.stubGlobal(
    'fetch',
    vi.fn((request: Request) =>
      Promise.resolve(
        new Response(JSON.stringify(request.url.includes('/source') ? SOURCE : []), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    ),
  )
  usePrefs.setState({ listWidth: DEFAULT_LIST_WIDTH, listCollapsed: false })
  useUi.setState({
    focus: 'list',
    runFilter: { workflow: ALL_WORKFLOWS, query: '' },
    logComposerFor: null,
  })
}

describe('App', () => {
  beforeEach(freshTab)

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('renders the four regions of 10 §Layout', () => {
    shell()

    expect(screen.getByRole('banner')).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'runs' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'detail' })).toBeInTheDocument()
    expect(screen.getByRole('contentinfo')).toBeInTheDocument()
  })

  it('hangs the list and the detail pane off the splitter', () => {
    shell()

    // The width between them is the splitter's, and so is the rail; the
    // shell only says which side each region goes.
    expect(screen.getByTestId('list-panel')).toContainElement(
      screen.getByRole('region', { name: 'runs' }),
    )
    expect(screen.getByTestId('detail-panel')).toContainElement(
      screen.getByRole('region', { name: 'detail' }),
    )
    expect(screen.getByRole('separator', { name: 'resize run list' })).toBeInTheDocument()
  })

  it('shows the rail in place of the list when it is collapsed', () => {
    usePrefs.setState({ listCollapsed: true })
    shell()

    expect(screen.queryByRole('region', { name: 'runs' })).toBeNull()
    expect(screen.getByRole('button', { name: 'show run list' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'detail' })).toBeInTheDocument()
  })

  it('counts the rows on screen in the strip and the header', () => {
    shell()

    expect(screen.getByTestId('rows-shown')).toHaveTextContent('2 shown')
    expect(screen.getByTestId('run-count')).toHaveTextContent('2 runs')
    expect(screen.getByTestId('active-count')).toHaveTextContent('1 active')
  })

  it('counts them in the collapsed rail too', () => {
    usePrefs.setState({ listCollapsed: true })
    shell()

    expect(screen.getByTestId('runs-rail')).toHaveTextContent('RUNS 2')
  })

  it('narrows the rows as the header’s `/` input is typed into', () => {
    shell()
    expect(rows()).toHaveLength(2)

    // `fireEvent`, not `userEvent`: jsdom performs no layout, so every
    // element's box is 0×0 at the origin and the resizable group reads a
    // pointer press anywhere as a press on its handle, taking the focus
    // the keystrokes would have gone to. Typing itself is exercised on
    // `RunFilters`, which has no splitter beside it.
    fireEvent.change(screen.getByRole('textbox', { name: 'filter runs' }), {
      target: { value: 'squirrels' },
    })

    expect(rows()).toHaveLength(1)
    expect(rows()[0]).toHaveTextContent('squirrels vs chipmunks')
    expect(screen.getByTestId('rows-shown')).toHaveTextContent('1 shown')
    // The header's count is the server's, not the filter's.
    expect(screen.getByTestId('run-count')).toHaveTextContent('2 runs')
  })

  it('narrows the rows from a workflow chip', async () => {
    shell()

    await userEvent.click(screen.getByRole('radio', { name: 'gamedev' }))

    expect(rows()).toHaveLength(1)
    expect(rows()[0]).toHaveTextContent('squirrels vs chipmunks')
  })

  it('draws the run `?run=` names as the selected one', () => {
    shell({ run: 'cccc3333dddd' })

    expect(rows()[0]).toHaveAttribute('aria-selected', 'false')
    expect(rows()[1]).toHaveAttribute('aria-selected', 'true')
  })

  it('hands a clicked row to the route, which writes `?run=`', async () => {
    const onSelectRun = vi.fn()
    shell({}, { onSelectRun })

    await userEvent.click(rows()[0]!)
    expect(onSelectRun).toHaveBeenCalledWith('aaaa1111bbbb')
  })

  it('passes the selected run through to the pane bar', () => {
    shell({ run: 'a4c81f20b91e' })

    expect(screen.getByTestId('selected-run')).toHaveTextContent('a4c81f20b91e')
  })

  it('asks for the palette from the footer', async () => {
    const onOpenPalette = vi.fn()
    const queryClient = new QueryClient({
      defaultOptions: { queries: { staleTime: 5000, retry: false } },
    })
    queryClient.setQueryData(listRunsApiRunsGetQueryKey(), RUNS)
    queryClient.setQueryData(manifestApiPluginsGetQueryKey(), MANIFEST)
  queryClient.setQueryData(listWorkflowsApiWorkflowsGetQueryKey(), WORKFLOWS)
    render(
      <QueryClientProvider client={queryClient}>
        <App
          search={{}}
          onSelectRun={() => {}}
          onSelectPane={() => {}}
          onOpenPalette={onOpenPalette}
        />
      </QueryClientProvider>,
    )

    await userEvent.click(screen.getByRole('button', { name: /palette/ }))
    expect(onOpenPalette).toHaveBeenCalledOnce()
  })

  it('draws the palette only when `?overlay=palette` says so', () => {
    shell()
    expect(screen.queryByTestId('palette')).toBeNull()

    cleanup()
    shell({ overlay: 'palette' })
    expect(screen.getByTestId('palette')).toBeInTheDocument()
  })

  it('draws the new run overlay only when `?overlay=new` says so', async () => {
    shell()
    expect(screen.queryByTestId('new-run')).toBeNull()

    cleanup()
    shell({ overlay: 'new' })
    expect(screen.getByTestId('new-run')).toBeInTheDocument()
    // Over the cached workflows, so it is the form and not the notice.
    expect(await screen.findByTestId('new-run-form')).toBeInTheDocument()
  })

  it('draws the workflow library only when `?overlay=library` says so', async () => {
    shell()
    expect(screen.queryByTestId('library')).toBeNull()

    cleanup()
    shell({ overlay: 'library', run: 'aaaa1111bbbb', node: 'prepare' })
    expect(screen.getByTestId('library')).toBeInTheDocument()

    // Over the cached workflows and sources, so it is the viewer and not
    // a notice — and `?node=` is the line it landed on, which is what
    // makes the graph pane's `open definition` land on a definition.
    const viewer = await screen.findByTestId('library-source')
    expect(viewer).toHaveTextContent('def prepare(ctx):')
    expect(viewer.querySelector('[data-anchor="true"]')).toHaveAttribute(
      'data-line',
      '1',
    )
  })

  it('draws the edit overlay only when `?overlay=edit` says so', async () => {
    shell()
    expect(screen.queryByTestId('edit-run')).toBeNull()

    cleanup()
    shell({ overlay: 'edit', run: 'aaaa1111bbbb' })
    expect(screen.getByTestId('edit-run')).toBeInTheDocument()
    // Over the cached run, so it is the form and not the notice, opened
    // on the title and description the run already has.
    expect(await screen.findByTestId('edit-run-form')).toBeInTheDocument()
    expect(screen.getByLabelText('TITLE')).toHaveValue('rebuild run detail')
  })

  it('draws a picker only when one of the four `?overlay=` names it', async () => {
    shell({ overlay: 'edit', run: 'aaaa1111bbbb' })
    expect(screen.queryByTestId('picker')).toBeNull()

    cleanup()
    shell({ overlay: 'pick-retry', run: 'aaaa1111bbbb' })
    const picker = screen.getByTestId('picker')
    // Over the cached run detail, so it is the attempt list: `prepare`
    // failed, which is an attempt that has stopped.
    expect(await within(picker).findByText('prepare')).toBeInTheDocument()
    expect(picker.querySelector('[data-task="7"]')).not.toBeNull()
  })

  it('draws the task drawer only when `?overlay=task&task=` says so', async () => {
    shell({ run: 'aaaa1111bbbb', task: 7 })
    expect(screen.queryByTestId('task-drawer')).toBeNull()

    cleanup()
    shell({ overlay: 'task', run: 'aaaa1111bbbb', task: 7 })
    // Over the cached attempt, so it is the panel and not the notice.
    expect(await screen.findByTestId('task-lineage')).toHaveTextContent(
      'the run’s first attempt',
    )
    expect(screen.getByTestId('task-error')).toHaveTextContent('the gate is red')
  })

  it('hands `focus stream` the attempt and the agent pane’s index', async () => {
    const onFocusStream = vi.fn()
    shell({ overlay: 'task', run: 'aaaa1111bbbb', task: 7 }, { onFocusStream })

    await userEvent.click(await screen.findByTestId('task-focus-stream'))

    // The index is looked up in the manifest rather than assumed: a
    // plugin's own `agent` panel is not this one (09 §Builtins).
    expect(onFocusStream).toHaveBeenCalledExactlyOnceWith(7, AGENT_PANE_INDEX)
  })

  it('draws the keys overlay only when `?overlay=keys` says so', () => {
    shell()
    expect(screen.queryByTestId('keys')).toBeNull()

    cleanup()
    shell({ overlay: 'keys' })
    expect(
      screen.getByTestId('keys').querySelectorAll('[data-binding]'),
    ).toHaveLength(KEY_BINDINGS.length)
  })

  it('draws the delete confirm only when `?overlay=delete` says so', () => {
    shell({ run: 'aaaa1111bbbb' })
    expect(screen.queryByTestId('delete-run')).toBeNull()

    cleanup()
    shell({ overlay: 'delete', run: 'aaaa1111bbbb' })
    expect(screen.getByTestId('delete-run')).toHaveTextContent('cannot be undone')
  })

  it('disables pause / resume for a run in neither state', () => {
    // The second seeded run is `completed`, which 04 makes neither
    // pausable nor resumable; the first is `running`.
    shell({ overlay: 'palette', run: 'aaaa1111bbbb' })
    expect(command('pause / resume run')).toHaveAttribute('data-disabled', 'false')

    cleanup()
    shell({ overlay: 'palette', run: 'cccc3333dddd' })
    expect(command('pause / resume run')).toHaveAttribute('data-disabled', 'true')
  })

  it('opens the workflow library from the header’s workflows button', async () => {
    const onOpenOverlay = vi.fn()
    shell({}, { onOpenOverlay })

    await userEvent.click(screen.getByRole('button', { name: 'workflows' }))

    expect(onOpenOverlay).toHaveBeenCalledExactlyOnceWith('library')
  })

  it('opens the new run overlay from the header’s ＋ new run', async () => {
    const onOpenOverlay = vi.fn()
    shell({}, { onOpenOverlay })

    await userEvent.click(screen.getByRole('button', { name: 'new run' }))

    expect(onOpenOverlay).toHaveBeenCalledExactlyOnceWith('new')
  })

  it('lists every command of the catalogue, with its key', () => {
    shell({ overlay: 'palette' })

    expect(screen.getAllByRole('option')).toHaveLength(PALETTE_COMMANDS.length)
    for (const { name, hint, key } of PALETTE_COMMANDS) {
      const row = command(name)
      expect(within(row).getByText(hint)).toBeInTheDocument()
      expect(within(row).getByText(key)).toBeInTheDocument()
    }
  })

  it('opens another overlay from the palette, without closing it first', async () => {
    const onOpenOverlay = vi.fn()
    const onCloseOverlay = vi.fn()
    shell({ overlay: 'palette' }, { onOpenOverlay, onCloseOverlay })

    await userEvent.click(command('open workflow library'))

    expect(onOpenOverlay).toHaveBeenCalledExactlyOnceWith('library')
    expect(onCloseOverlay).not.toHaveBeenCalled()
  })

  it('refetches everything this tab holds, and closes', async () => {
    const onCloseOverlay = vi.fn()
    const { queryClient } = shell({ overlay: 'palette' }, { onCloseOverlay })
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')

    await userEvent.click(command('refresh'))

    expect(invalidate).toHaveBeenCalledOnce()
    expect(onCloseOverlay).toHaveBeenCalledOnce()
  })

  it('collapses the run list to its rail, and closes', async () => {
    const onCloseOverlay = vi.fn()
    shell({ overlay: 'palette' }, { onCloseOverlay })

    await userEvent.click(command('toggle list'))

    expect(usePrefs.getState().listCollapsed).toBe(true)
    expect(onCloseOverlay).toHaveBeenCalledOnce()
  })

  it('shows the log pane and asks for its composer, and closes', async () => {
    const onCloseOverlay = vi.fn()
    const onSelectPane = vi.fn()
    shell(
      { overlay: 'palette', run: 'aaaa1111bbbb' },
      { onCloseOverlay, onSelectPane },
    )

    await userEvent.click(command('append log'))

    // The log is the second builtin run pane of the manifest above, and
    // the index is looked up rather than assumed: `append log` writes no
    // note itself, it puts the operator in the box that does.
    expect(onSelectPane).toHaveBeenCalledExactlyOnceWith(1)
    expect(useUi.getState().logComposerFor).toBe('aaaa1111bbbb')
    expect(onCloseOverlay).toHaveBeenCalledOnce()
  })

  it('asks for no composer when append log has no run', async () => {
    shell({ overlay: 'palette' })

    await userEvent.click(command('append log'))

    expect(useUi.getState().logComposerFor).toBeNull()
  })

  it('disables the run-scoped commands until a run is selected', () => {
    shell({ overlay: 'palette' })

    expect(command('retry task')).toHaveAttribute('aria-disabled', 'true')
    expect(command('new run')).not.toHaveAttribute('aria-disabled', 'true')

    cleanup()
    shell({ overlay: 'palette', run: 'aaaa1111bbbb' })

    expect(command('retry task')).not.toHaveAttribute('aria-disabled', 'true')
  })

  it('opens a picker on the selected run', async () => {
    const onOpenOverlay = vi.fn()
    shell({ overlay: 'palette', run: 'aaaa1111bbbb' }, { onOpenOverlay })

    await userEvent.click(command('retry task'))

    expect(onOpenOverlay).toHaveBeenCalledExactlyOnceWith('pick-retry')
  })
})

/* -------------------------------------------------------------------- */
/* The plugin actions the manifest contributes to the palette (T070)     */
/* -------------------------------------------------------------------- */

/**
 * `plugin: <workflow>`: the section T066a left empty
 * (`overlays/pluginActions.ts`, 09 §Declarations).
 *
 * What is asserted here is the shell's half — that the rows come from
 * the manifest under the selected run's ownership, and that selecting
 * one opens the action overlay. The rows themselves are
 * `overlays/__tests__/pluginActions.test.ts`'s.
 */
describe('the palette’s plugin actions', () => {
  /** The selected run's workflow, with one action per relevant scope. */
  const WITH_ACTIONS: PluginManifestEntry[] = [
    ...MANIFEST,
    {
      workflow: 'feature_build',
      actions: [
        {
          name: 'override',
          title: 'Override secret word',
          scope: 'run',
          confirm: true,
          schema: { type: 'object', properties: {} },
        },
        {
          name: 'flag',
          title: 'Flag this attempt',
          scope: 'task',
          confirm: false,
          schema: { type: 'object', properties: {} },
        },
      ],
    },
    {
      workflow: 'gamedev',
      actions: [
        {
          name: 'reseed',
          title: 'Reseed the dictionary',
          scope: 'global',
          confirm: false,
          schema: { type: 'object', properties: {} },
        },
      ],
    },
  ]

  it('lists the selected run’s workflow’s actions, and no other’s', () => {
    shell(
      { overlay: 'palette', run: 'aaaa1111bbbb' },
      { manifest: WITH_ACTIONS },
    )

    const group = screen.getByRole('group', { name: 'plugin: feature_build' })
    expect(within(group).getAllByRole('option')).toHaveLength(2)
    // `gamedev` owns no run in this list, so its section is not drawn.
    expect(
      screen.queryByRole('group', { name: 'plugin: gamedev' }),
    ).not.toBeInTheDocument()
  })

  it('opens the action overlay from a row', async () => {
    const onOpenAction = vi.fn()
    shell(
      { overlay: 'palette', run: 'aaaa1111bbbb' },
      { manifest: WITH_ACTIONS, onOpenAction },
    )

    await userEvent.click(command('Override secret word'))

    expect(onOpenAction).toHaveBeenCalledExactlyOnceWith('feature_build:override')
  })

  it('disables a row the selection cannot satisfy, and opens nothing', async () => {
    const onOpenAction = vi.fn()
    shell(
      { overlay: 'palette', run: 'aaaa1111bbbb' },
      { manifest: WITH_ACTIONS, onOpenAction },
    )

    // `flag` is task-scoped and `?task=` names no attempt: the row is
    // listed, because the palette is the app's index of itself, and it
    // does nothing.
    await userEvent.click(command('Flag this attempt'))

    expect(onOpenAction).not.toHaveBeenCalled()
  })

  it('draws the action overlay only when `?overlay=action` says so', () => {
    shell({ run: 'aaaa1111bbbb' }, { manifest: WITH_ACTIONS })
    expect(screen.queryByTestId('plugin-action')).toBeNull()

    cleanup()
    shell(
      { overlay: 'action', action: 'feature_build:override', run: 'aaaa1111bbbb' },
      { manifest: WITH_ACTIONS },
    )
    expect(screen.getByTestId('plugin-action')).toBeInTheDocument()
    expect(screen.getByTestId('action-runner')).toHaveAttribute(
      'data-action',
      'override',
    )
  })
})

/* -------------------------------------------------------------------- */
/* The run operations behind the palette's own rows                      */
/* -------------------------------------------------------------------- */

/**
 * The four rows that call an endpoint rather than opening something
 * (`overlays/runOps.ts`, 08 §Runs).
 *
 * `useRunOps` is tested on its own; what is asserted here is the shell's
 * half — which run each row is bound to, and that a row with no run
 * selected posts nothing rather than a request with `undefined` in the
 * path.
 */
describe('the run operations', () => {
  beforeEach(freshTab)

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  /** The POSTs made so far, in order. */
  function posted(): string[] {
    return vi
      .mocked(fetch)
      .mock.calls.map(([input]) => input as unknown as Request)
      .filter((request) => request.method === 'POST')
      .map((request) => new URL(request.url, 'http://localhost').pathname)
  }

  it.each([
    ['pause / resume run', `/api/runs/aaaa1111bbbb/pause`],
    ['cancel run', `/api/runs/aaaa1111bbbb/cancel`],
    ['move run up', `/api/runs/aaaa1111bbbb/position`],
    ['move run down', `/api/runs/aaaa1111bbbb/position`],
  ])('runs %s against the selected run', async (name, path) => {
    shell({ overlay: 'palette', run: 'aaaa1111bbbb' })

    await userEvent.click(command(name))

    await waitFor(() => {
      expect(posted()).toEqual([path])
    })
  })

  it('resumes the run the list says is paused', async () => {
    // One key over two endpoints: the run's own status picks the call
    // (04 §Operator operations), and the status comes off `GET /api/runs`.
    shell(
      { overlay: 'palette', run: 'aaaa1111bbbb' },
      { runs: [{ ...RUNS[0]!, status: 'paused' }] },
    )

    await userEvent.click(command('pause / resume run'))

    await waitFor(() => {
      expect(posted()).toEqual(['/api/runs/aaaa1111bbbb/resume'])
    })
  })

  it.each(['pause / resume run', 'cancel run', 'move run up', 'move run down'])(
    'posts nothing for %s with no run selected',
    async (name) => {
      shell({ overlay: 'palette' })

      await userEvent.click(command(name))

      expect(posted()).toEqual([])
    },
  )
})

/* -------------------------------------------------------------------- */
/* The graph pane's two handovers                                        */
/* -------------------------------------------------------------------- */

/**
 * 10 §Graph pane: a row "jumps to the log pane filtered to that node",
 * and `open definition` opens the library.
 *
 * Both are the graph rail's clicks and the shell's answers. The shell's
 * half is the one thing neither `GraphRail.test.tsx` nor the route can
 * assert: **which** pane index the node goes with, which is the log
 * pane of *this* selection's cycle rather than a number written down.
 */
describe('the graph pane’s handovers', () => {
  /** A cycle whose log pane is second and whose graph pane is third. */
  const WITH_GRAPH: PluginManifestEntry[] = [
    {
      workflow: '_builtin',
      panels: [
        { name: 'overview', slot: 'run', placement: 'pane', scope: 'run', kind: 'custom' },
        { name: 'log', slot: 'run', placement: 'pane', scope: 'run', kind: 'custom' },
        {
          name: 'graph',
          slot: 'run',
          placement: 'pane',
          scope: 'run',
          kind: 'custom',
          element: 'ath-run-graph',
        },
      ],
    },
  ]

  /** The same cycle with no log pane in it at all. */
  const WITHOUT_LOG: PluginManifestEntry[] = [
    {
      workflow: '_builtin',
      panels: (WITH_GRAPH[0]?.panels ?? []).filter((entry) => entry.name !== 'log'),
    },
  ]

  beforeEach(freshTab)

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('hands a clicked node the index of this cycle’s log pane', async () => {
    const onOpenNode = vi.fn()
    shell(
      { run: 'aaaa1111bbbb', pane: 2 },
      { manifest: WITH_GRAPH, onOpenNode },
    )

    fireEvent.click(await screen.findByTestId('graph-row'))

    // The log is the second pane of the manifest above, and the index is
    // looked up rather than assumed (09 §Builtins are plugins).
    expect(onOpenNode).toHaveBeenCalledExactlyOnceWith('prepare', 1)
  })

  it('hands over no pane at all when the cycle has no log pane', async () => {
    const onOpenNode = vi.fn()
    shell(
      { run: 'aaaa1111bbbb', pane: 1 },
      { manifest: WITHOUT_LOG, onOpenNode },
    )

    fireEvent.click(await screen.findByTestId('graph-row'))

    expect(onOpenNode).toHaveBeenCalledExactlyOnceWith('prepare', undefined)
  })

  it('opens the workflow library from `open definition`', async () => {
    const onOpenOverlay = vi.fn()
    shell(
      { run: 'aaaa1111bbbb', pane: 2 },
      { manifest: WITH_GRAPH, onOpenOverlay },
    )

    fireEvent.click(await screen.findByTestId('graph-open-definition'))

    expect(onOpenOverlay).toHaveBeenCalledExactlyOnceWith('library')
  })
})

/* -------------------------------------------------------------------- */
/* The keyboard map (T067)                                               */
/* -------------------------------------------------------------------- */

/**
 * 10 §Keyboard, over the real shell.
 *
 * `keys/__tests__/useKeymap.test.tsx` asserts the table and the scoping
 * against a harness; what is asserted here is the wiring — that the key
 * reaches the same action the palette row does, over the same model.
 */
describe('the keyboard map', () => {
  beforeEach(freshTab)

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  /** Press a plain key on the page itself, as an operator would. */
  function press(key: string, init: Partial<KeyboardEventInit> = {}) {
    fireEvent.keyDown(document.body, { key, ...init })
  }

  it('opens the delete confirm on `D`, and nothing at all on `d`', () => {
    const onOpenOverlay = vi.fn()
    shell({ run: 'aaaa1111bbbb' }, { onOpenOverlay })

    // D51: `d` is the request panel's deny and reaches nothing else, so
    // a `d` meant for it one focus ring away destroys nothing.
    press('d')
    expect(onOpenOverlay).not.toHaveBeenCalled()

    press('D', { shiftKey: true })
    expect(onOpenOverlay).toHaveBeenCalledExactlyOnceWith('delete')
  })

  it('opens the overlays 10 §Keyboard names', () => {
    const onOpenOverlay = vi.fn()
    shell({ run: 'aaaa1111bbbb' }, { onOpenOverlay })

    for (const [key, overlay] of [
      ['n', 'new'],
      ['w', 'library'],
      ['e', 'edit'],
      ['?', 'keys'],
      ['t', 'pick-retry'],
      ['m', 'pick-move'],
      ['x', 'pick-cancel'],
      ['r', 'pick-rerun'],
    ]) {
      press(key!)
      expect(onOpenOverlay, `\`${key!}\` opens ${overlay!}`).toHaveBeenCalledWith(
        overlay,
      )
    }
  })

  it('selects the next and previous row with `j`/`k`, clamped', () => {
    const onSelectRun = vi.fn()
    shell({ run: 'aaaa1111bbbb' }, { onSelectRun })

    press('j')
    expect(onSelectRun).toHaveBeenCalledExactlyOnceWith('cccc3333dddd')

    // The first row is the top: `k` there stays, as the mock's `move`
    // does, rather than wrapping to the bottom of the list.
    onSelectRun.mockClear()
    press('k')
    expect(onSelectRun).not.toHaveBeenCalled()
  })

  it('selects the first row when nothing is selected yet', () => {
    const onSelectRun = vi.fn()
    shell({}, { onSelectRun })

    press('ArrowDown')
    expect(onSelectRun).toHaveBeenCalledExactlyOnceWith('aaaa1111bbbb')
  })

  it('cycles the panes with `←`/`→` and jumps with `1`–`9`', () => {
    const onSelectPane = vi.fn()
    shell({ run: 'aaaa1111bbbb' }, { onSelectPane })

    press('ArrowRight')
    expect(onSelectPane).toHaveBeenLastCalledWith(1)

    // Three panes in the manifest above, so `←` from the first wraps.
    press('ArrowLeft')
    expect(onSelectPane).toHaveBeenLastCalledWith(2)

    press('3')
    expect(onSelectPane).toHaveBeenLastCalledWith(2)

    // `1`–`9` reaches a pane or nothing: there is no fourth.
    onSelectPane.mockClear()
    press('4')
    expect(onSelectPane).not.toHaveBeenCalled()
  })

  it('collapses the run list on `b`', () => {
    shell()
    expect(usePrefs.getState().listCollapsed).toBe(false)

    press('b')
    expect(usePrefs.getState().listCollapsed).toBe(true)
  })

  it('puts the caret in the log composer on `l`', () => {
    const onSelectPane = vi.fn()
    shell({ run: 'aaaa1111bbbb' }, { onSelectPane })

    press('l')

    expect(onSelectPane).toHaveBeenCalledExactlyOnceWith(1)
    expect(useUi.getState().logComposerFor).toBe('aaaa1111bbbb')
  })

  it('refetches everything this tab holds on `^r`', () => {
    const { queryClient } = shell()
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')

    press('r', { ctrlKey: true })

    // Every entry, with no key: `refresh` is the whole cache (10
    // §Realtime and caching).
    expect(invalidate).toHaveBeenCalledExactlyOnceWith()
  })

  it('opens the palette on `^p`', () => {
    const onOpenPalette = vi.fn()
    const queryClient = new QueryClient({
      defaultOptions: { queries: { staleTime: 5000, retry: false } },
    })
    queryClient.setQueryData(listRunsApiRunsGetQueryKey(), RUNS)
    queryClient.setQueryData(manifestApiPluginsGetQueryKey(), MANIFEST)
    render(
      <QueryClientProvider client={queryClient}>
        <App
          search={{}}
          onSelectRun={() => {}}
          onSelectPane={() => {}}
          onOpenPalette={onOpenPalette}
        />
      </QueryClientProvider>,
    )

    fireEvent.keyDown(document.body, { key: 'p', ctrlKey: true })
    expect(onOpenPalette).toHaveBeenCalledOnce()
  })

  it('closes the open overlay on `esc`, and closes nothing when none is', () => {
    const onCloseOverlay = vi.fn()
    shell({ overlay: 'keys' }, { onCloseOverlay })

    fireEvent.keyDown(document.body, { key: 'Escape' })
    expect(onCloseOverlay).toHaveBeenCalled()

    cleanup()
    onCloseOverlay.mockClear()
    shell({}, { onCloseOverlay })

    fireEvent.keyDown(document.body, { key: 'Escape' })
    expect(onCloseOverlay).not.toHaveBeenCalled()
  })

  it('hands the keyboard to the detail pane on `⏎`', () => {
    shell({ run: 'aaaa1111bbbb' })
    expect(useUi.getState().focus).toBe('list')

    fireEvent.keyDown(screen.getByRole('region', { name: 'runs' }), { key: 'Enter' })

    expect(useUi.getState().focus).toBe('detail')
    expect(document.activeElement).toBe(screen.getByRole('region', { name: 'detail' }))
  })

  it('is off while the operator is typing into the `/` input', () => {
    const onOpenOverlay = vi.fn()
    const onSelectRun = vi.fn()
    shell({ run: 'aaaa1111bbbb' }, { onOpenOverlay, onSelectRun })

    const input = screen.getByRole('textbox', { name: 'filter runs' })
    for (const key of ['n', 'D', 'j', 'w']) fireEvent.keyDown(input, { key })

    expect(onOpenOverlay).not.toHaveBeenCalled()
    expect(onSelectRun).not.toHaveBeenCalled()
  })

  it('is off while an overlay owns the keyboard', () => {
    const onOpenOverlay = vi.fn()
    const onSelectRun = vi.fn()
    shell({ run: 'aaaa1111bbbb', overlay: 'keys' }, { onOpenOverlay, onSelectRun })

    press('n')
    press('D', { shiftKey: true })
    press('j')

    expect(onOpenOverlay).not.toHaveBeenCalled()
    expect(onSelectRun).not.toHaveBeenCalled()
  })

  it('binds every keycap of `lib/keys.ts` that names an action', () => {
    // The table is the contract (10 §Keyboard is exhaustive), so the
    // check is that nothing in it is drawn in the footer and the `?`
    // overlay without something behind it. The four navigation rows and
    // the two request-panel rows are asserted above and in
    // `keys/__tests__`; the rest are palette commands.
    const commands = new Set(PALETTE_COMMANDS.map((one) => one.key))
    const navigation = new Set(['↑', '↓', 'j', 'k', '←', '→', '1–9', '⏎', 'tab'])
    const scoped = new Set(['a', 'd'])
    const app = new Set(['^p', 'esc'])

    for (const binding of KEY_BINDINGS) {
      for (const cap of binding.keys) {
        expect(
          commands.has(cap) || navigation.has(cap) || scoped.has(cap) || app.has(cap),
          `\`${cap}\` is bound to something`,
        ).toBe(true)
      }
    }
  })
})

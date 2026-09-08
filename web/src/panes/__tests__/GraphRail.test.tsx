/**
 * The graph pane: the order the rows come in, the sub-lists a fan-out
 * opens, the rails a loop draws, and what the detail column says
 * (`docs/v1/10-frontend.md` §Graph pane, `docs/v1/08-api.md` §Graph
 * semantics).
 *
 * Three fixtures, which are the three shapes a run can have (T063e):
 * linear with a loop-back, a fan-out that never closes, and the same
 * fan-out closed by a join. Between them they cover every rule the rail
 * has — a node drawn once per branch it ran in, a join drawn back at the
 * parent indent with the branches arriving into it, and a rail that
 * spans from the node a loop points at down to the node it leaves.
 *
 * Four things this suite is deliberately strict about:
 *
 * - **the row order is the route's.** `GET /api/runs/{id}/graph` sends
 *   the nodes in generation order and the pane draws the list it is
 *   given (08); what the pane adds is the *grouping*, and a sub-list
 *   lands where its first node does.
 * - **two branches of one fan-out are two sub-lists.** They carry the
 *   same `from_task` on the wire, so a renderer that grouped by
 *   `from_task` alone would draw one — which is why `render` and
 *   `report` each appear twice in the fan-out fixtures.
 * - **`k of n arrived` is the join's, and only while a fan-out is
 *   open.** It comes from `arrivals`, which the server computes; nothing
 *   here counts branches.
 * - **nothing is zero-filled.** A node no agent measured shows what was
 *   measured and no more, and an idle node's detail column is empty
 *   rather than `0 · 0s` (01 §Real data only).
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createAppQueryClient } from '../../api/client'
import {
  getGraphApiRunsRunIdGraphGetQueryKey,
  getRunApiRunsRunIdGetQueryKey,
  getSourceApiWorkflowsNameSourceGetQueryKey,
} from '../../api/gen/@tanstack/react-query.gen'
import type { GraphOut, RunDetail } from '../../api/gen/types.gen'
import {
  GraphRail,
  branchState,
  legendRows,
  moveRefusal,
  nodeDetail,
  railRows,
} from '../kinds'
import {
  FANOUT_GRAPH,
  GRAPH_RUN,
  JOINED_GRAPH,
  LINEAR_GRAPH,
  WORKFLOW_SOURCE,
  fannedRun,
  graphNode,
  linearRun,
} from './fixtures'

let queryClient: QueryClient

/** The clock the `attempt n · elapsed` detail is measured against. */
const NOW = Date.parse('2026-09-08T09:01:45Z')

/** Answer every request with `body`, and record the URLs asked for. */
function stubFetch(body: unknown, status = 200) {
  const urls: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (req: Request) => {
      urls.push(req.url)
      return new Response(JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
  return urls
}

/** The pane over a seeded graph, so nothing is fetched while it draws. */
function draw(
  graph: GraphOut | null = LINEAR_GRAPH,
  detail: RunDetail | null = linearRun(),
  options: {
    runId?: string | undefined
    taskId?: number | undefined
    onOpenNode?: ((node: string) => void) | undefined
    onOpenLibrary?: (() => void) | undefined
    source?: unknown
  } = {},
) {
  // `'runId' in options` and not a default parameter: passing
  // `undefined` explicitly is the case with no run selected.
  const runId = 'runId' in options ? options.runId : GRAPH_RUN
  if (runId !== undefined) {
    if (graph !== null) {
      queryClient.setQueryData(
        getGraphApiRunsRunIdGraphGetQueryKey({ path: { run_id: runId } }),
        graph,
      )
    }
    if (detail !== null) {
      queryClient.setQueryData(
        getRunApiRunsRunIdGetQueryKey({ path: { run_id: runId } }),
        detail,
      )
      queryClient.setQueryData(
        getSourceApiWorkflowsNameSourceGetQueryKey({ path: { name: detail.workflow } }),
        options.source ?? WORKFLOW_SOURCE,
      )
    }
  }

  return render(
    <QueryClientProvider client={queryClient}>
      <GraphRail
        runId={runId}
        taskId={options.taskId}
        onOpenNode={options.onOpenNode}
        onOpenLibrary={options.onOpenLibrary}
      />
    </QueryClientProvider>,
  )
}

/** The rows in the order they are drawn. */
function rows() {
  return screen.getAllByTestId('graph-row')
}

/** The node names in the order they are drawn. */
function names() {
  return rows().map((row) => row.getAttribute('data-node'))
}

/** The row for one node, by name; the first when it is drawn twice. */
function row(node: string): HTMLElement {
  const found = rows().find((element) => element.getAttribute('data-node') === node)
  if (found === undefined) throw new Error(`no row for ${node}`)
  return found
}

/** The detail column of a row, or `null` when it draws none. */
function detailOf(element: HTMLElement): string | null {
  return element.querySelector('[data-testid="graph-detail"]')?.textContent ?? null
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(NOW)
  queryClient = createAppQueryClient()
  // What is seeded is kept: nothing here refetches.
  queryClient.setDefaultOptions({ queries: { retry: false, staleTime: Infinity } })
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

/* -------------------------------------------------------------------- */
/* The row order                                                         */
/* -------------------------------------------------------------------- */

describe('the order of the rows', () => {
  it('draws a linear graph in the generation order the route sent', () => {
    draw()
    expect(names()).toEqual(['prompt', 'engineering', 'review', 'qa', 'git'])
  })

  it('draws each branch of a fan-out as its own sub-list, in order', () => {
    draw(FANOUT_GRAPH, fannedRun())
    // `plan` fanned out; each of the two branches ran `render` then
    // `report`, so each node is drawn once per branch and the branches
    // are consecutive.
    expect(names()).toEqual(['plan', 'render', 'report', 'render', 'report'])
    expect(rows().map((element) => element.getAttribute('data-depth'))).toEqual([
      '0',
      '1',
      '1',
      '1',
      '1',
    ])
  })

  it('closes the sub-lists with the join, back at the parent indent', () => {
    draw(JOINED_GRAPH, fannedRun())
    expect(names()).toEqual(['plan', 'render', 'report', 'render', 'report', 'merge'])
    expect(row('merge').getAttribute('data-depth')).toBe('0')
  })

  it('keeps a node the run has not reached at the parent indent', () => {
    // `qa` and `git` are idle in the linear fixture: no attempt has ever
    // existed, so there is no branch to nest them in.
    draw()
    expect(row('qa').getAttribute('data-depth')).toBe('0')
  })
})

/* -------------------------------------------------------------------- */
/* The sub-lists                                                         */
/* -------------------------------------------------------------------- */

describe('the sub-lists a fan-out opens', () => {
  it('keys them by the fan-out and the branch, not by the fan-out alone', () => {
    draw(FANOUT_GRAPH, fannedRun())
    expect(rows().map((element) => element.getAttribute('data-branch'))).toEqual([
      null,
      '601:0',
      '601:0',
      '601:1',
      '601:1',
    ])
  })

  it('labels each sub-list with its branch, its key and the fan-out', () => {
    draw(FANOUT_GRAPH, fannedRun())
    const labels = screen.getAllByTestId('graph-branch-label')
    expect(labels.map((label) => label.textContent)).toEqual([
      'branch 1 of 2 · alpha · from task 601',
      'branch 2 of 2 · beta · from task 601',
    ])
  })

  it('falls back to the position when the attempts have not arrived', () => {
    // `GraphBranch` alone cannot tell two branches of one fan-out apart
    // (08 §Graph semantics), so with no run detail the label says which
    // sub-list this is and no more.
    draw(FANOUT_GRAPH, null)
    expect(
      screen.getAllByTestId('graph-branch-label').map((label) => label.textContent),
    ).toEqual(['branch 1 · from task 601', 'branch 2 · from task 601'])
  })

  it('pairs a branch’s rows by their frames, not by their position', () => {
    // `report`'s entries arrive in the opposite order to `render`'s, so
    // a renderer that paired the two nodes' entries by position would
    // put branch 2's report under branch 1's render. The pairing is the
    // branch-frame stack on the attempts (08 §Graph semantics).
    draw(FANOUT_GRAPH, fannedRun())
    const reports = rows().filter(
      (element) => element.getAttribute('data-node') === 'report',
    )
    expect(reports.map((element) => element.getAttribute('data-branch'))).toEqual([
      '601:0',
      '601:1',
    ])
    // Branch 1's report took 5 s and branch 2's 3 s.
    expect(reports.map(detailOf)).toEqual(['5s', '3s'])
  })

  it('gives each branch row its own state, not the node’s', () => {
    // `render` is `in_progress` as a node while one of its two branches
    // is running and the other is done: two rows drawn with the node's
    // own glyph would each claim to be the running one.
    const graph = {
      ...FANOUT_GRAPH,
      nodes: FANOUT_GRAPH.nodes.map((node) =>
        node.name === 'render' ? { ...node, state: 'in_progress' as const } : node,
      ),
    }
    const detail = fannedRun()
    const tasks = (detail.tasks ?? []).map((task) =>
      task.id === 603
        ? { ...task, status: 'in_progress' as const, finished: null, stats: null }
        : task,
    )
    draw(graph, { ...detail, tasks })

    const rendered = rows().filter(
      (element) => element.getAttribute('data-node') === 'render',
    )
    expect(rendered.map((element) => element.getAttribute('data-state'))).toEqual([
      'done',
      'in_progress',
    ])
  })

  it('reads 08’s precedence over one branch’s attempts', () => {
    const attempt = (status: string) =>
      ({ status }) as unknown as Parameters<typeof branchState>[0][number]
    // A failed attempt with a retry queued reports `ready` (08).
    expect(branchState([attempt('failed'), attempt('ready')])).toBe('ready')
    expect(branchState([attempt('done'), attempt('in_progress')])).toBe('in_progress')
    expect(branchState([])).toBe('idle')
  })

  it('gives a branch row the detail of its own branch, not of the node', () => {
    draw(FANOUT_GRAPH, fannedRun())
    // Branch 1 ran `render` for 20 s on 4,000 tokens; branch 2 for 40 s
    // on 9,000. A row that summed the node would show 13,000 on both.
    const rendered = rows().filter(
      (element) => element.getAttribute('data-node') === 'render',
    )
    expect(rendered.map(detailOf)).toEqual(['4,000 · 20s', '9,000 · 40s'])
  })
})

/* -------------------------------------------------------------------- */
/* The rails                                                             */
/* -------------------------------------------------------------------- */

describe('the loop rail', () => {
  /** The rail cells, one per row, in draw order. */
  function rails() {
    return screen.getAllByTestId('graph-rail')
  }

  it('spans from the node a loop points at down to the node it leaves', () => {
    draw()
    // `review → engineering` and `qa → engineering`: the rail runs from
    // row 1 (engineering) to row 3 (qa), so the line leaves rows 1 and 2
    // downwards and arrives at rows 2 and 3 from above.
    expect(rails().map((cell) => cell.getAttribute('data-down'))).toEqual([
      'false',
      'true',
      'true',
      'false',
      'false',
    ])
    expect(rails().map((cell) => cell.getAttribute('data-up'))).toEqual([
      'false',
      'false',
      'true',
      'true',
      'false',
    ])
  })

  it('puts the ◀ on the node the back edges point at', () => {
    draw()
    expect(rails().map((cell) => cell.getAttribute('data-arrow'))).toEqual([
      'false',
      'true',
      'false',
      'false',
      'false',
    ])
  })

  it('labels the rail once, at the middle of its span', () => {
    draw()
    const labels = screen.getAllByTestId('graph-loop-label')
    expect(labels).toHaveLength(1)
    expect(labels[0]?.textContent).toBe('loop')
  })

  it('draws no rail at all on a graph with no back edge', () => {
    draw(FANOUT_GRAPH, fannedRun())
    expect(rails().every((cell) => cell.getAttribute('data-down') === 'false')).toBe(true)
    expect(screen.queryByTestId('graph-loop-label')).toBeNull()
  })

  it('skips a back edge whose ends this run has not drawn', () => {
    // An edge of the finalized graph naming a node the response does not
    // carry is drawn to nowhere rather than crashing the rail.
    const built = railRows(
      {
        nodes: [graphNode({ name: 'only', generation: 0 })],
        edges: [{ from: 'gone', to: 'only', kind: 'back', traversed: 1 }],
      },
      [],
      NOW,
    )
    expect(built).toHaveLength(1)
    expect(built[0]?.rail.arrow).toBe(false)
  })
})

/* -------------------------------------------------------------------- */
/* The connectors                                                        */
/* -------------------------------------------------------------------- */

describe('the connectors between the rows', () => {
  it('draws a ▼ under every row but the last', () => {
    draw()
    expect(screen.getAllByTestId('graph-connector')).toHaveLength(4)
    expect(screen.queryByTestId('graph-into-join')).toBeNull()
  })

  it('draws a ▲ from each sub-list into the join that closes it', () => {
    draw(JOINED_GRAPH, fannedRun())
    const arrows = screen.getAllByTestId('graph-into-join')
    expect(arrows).toHaveLength(2)
    expect(arrows.every((arrow) => arrow.textContent?.includes('▲'))).toBe(true)
  })

  it('draws no arrow out of a fan-out that no join closes', () => {
    draw(FANOUT_GRAPH, fannedRun())
    expect(screen.queryByTestId('graph-into-join')).toBeNull()
  })
})

/* -------------------------------------------------------------------- */
/* The glyphs and the detail column                                      */
/* -------------------------------------------------------------------- */

describe('the glyphs', () => {
  it('marks done, active, waiting and idle nodes', () => {
    draw()
    const glyph = (node: string) =>
      row(node).querySelector('[data-testid="graph-glyph"]')?.textContent
    expect(glyph('prompt')).toBe('✓')
    expect(glyph('engineering')).toBe('●')
    expect(glyph('review')).toBe('·')
    expect(glyph('qa')).toBe('·')
  })

  it('marks a join with ⋈ wherever its state is', () => {
    draw(JOINED_GRAPH, fannedRun())
    expect(row('merge').querySelector('[data-testid="graph-glyph"]')?.textContent).toBe(
      '⋈',
    )
  })

  it('pulses the node in progress and nothing else', () => {
    draw()
    const pulsing = screen
      .getAllByTestId('graph-glyph')
      .filter((glyph) => glyph.className.includes('animate-ath-pulse'))
    expect(pulsing).toHaveLength(1)
    expect(row('engineering')).toContainElement(pulsing[0] ?? null)
  })
})

describe('the detail column', () => {
  it('shows tokens · duration for what a node has spent', () => {
    draw()
    expect(detailOf(row('prompt'))).toBe('18,204 · 9s')
  })

  it('shows attempt n · elapsed while a node is in progress', () => {
    draw()
    // Attempt 2 was claimed at 09:00:00 and the clock is at 09:01:45.
    expect(detailOf(row('engineering'))).toBe('attempt 2 · 105s')
  })

  it('shows waiting for a node parked on a request', () => {
    draw()
    expect(detailOf(row('review'))).toBe('waiting')
  })

  it('shows k of n arrived on a join with a fan-out still open', () => {
    draw(JOINED_GRAPH, fannedRun())
    expect(detailOf(row('merge'))).toBe('1 of 2 arrived')
  })

  it('says nothing at all about a node the run has not reached', () => {
    draw()
    expect(detailOf(row('qa'))).toBeNull()
  })

  it('names the state when a node has attempts but nothing measured', () => {
    const node = graphNode({ name: 'gate', generation: 0, state: 'ready', attempts: 1 })
    expect(nodeDetail(node, 'ready', [], NOW)).toBe('ready')
  })

  it('drops the join arrivals once the fan-out has closed', () => {
    const node = graphNode({ name: 'merge', generation: 3, join: true, state: 'done' })
    expect(nodeDetail(node, 'done', [], NOW)).toBe('done')
  })
})

/* -------------------------------------------------------------------- */
/* The EDGES legend and the SOURCE                                       */
/* -------------------------------------------------------------------- */

describe('the EDGES block', () => {
  it('lists the graph’s arrows by kind, forward then loop then join', () => {
    draw(JOINED_GRAPH, fannedRun())
    const legend = screen.getAllByTestId('graph-legend-row')
    expect(legend.map((line) => line.getAttribute('data-kind'))).toEqual([
      'edge',
      'edge',
      'join',
    ])
    expect(legend.map((line) => line.textContent)).toEqual([
      'edgeplan → render',
      'edgerender → report',
      'joinreport → merge',
    ])
  })

  it('carries the loops and the nodes that are at a gate', () => {
    draw()
    const legend = screen.getAllByTestId('graph-legend-row')
    expect(legend.map((line) => line.getAttribute('data-kind'))).toEqual([
      'edge',
      'edge',
      'edge',
      'edge',
      'loop',
      'loop',
      'gate',
    ])
    expect(legend.at(-1)?.textContent).toBe('gatereview · waiting')
  })

  it('lists no kind the graph has none of', () => {
    expect(legendRows(FANOUT_GRAPH).map((line) => line.kind)).toEqual(['edge', 'edge'])
  })

  it('shows the file the workflow is defined in', () => {
    draw()
    expect(screen.getByTestId('graph-source')).toHaveTextContent(WORKFLOW_SOURCE.file)
  })

  it('opens the library from `open definition`', () => {
    const onOpenLibrary = vi.fn()
    draw(LINEAR_GRAPH, linearRun(), { onOpenLibrary })
    fireEvent.click(screen.getByTestId('graph-open-definition'))
    expect(onOpenLibrary).toHaveBeenCalledTimes(1)
  })
})

/* -------------------------------------------------------------------- */
/* Clicking and right-clicking                                           */
/* -------------------------------------------------------------------- */

describe('clicking a row', () => {
  it('jumps to the log pane filtered to that node', () => {
    const onOpenNode = vi.fn()
    draw(LINEAR_GRAPH, linearRun(), { onOpenNode })
    fireEvent.click(row('review'))
    expect(onOpenNode).toHaveBeenCalledWith('review')
  })
})

describe('the right-click menu', () => {
  it('offers rerun and move for the node it was opened on', () => {
    draw()
    fireEvent.contextMenu(row('engineering'))
    const menu = screen.getByTestId('graph-menu')
    expect(menu.getAttribute('data-node')).toBe('engineering')
    expect(screen.getByTestId('graph-menu-rerun')).toBeEnabled()
    // The focused attempt is `review`, the most recent one in flight —
    // an attempt parked on a request is still in flight (08 §Tasks).
    expect(screen.getByTestId('graph-menu-move')).toHaveTextContent('move task 704 here')
    expect(screen.getByTestId('graph-menu-move')).toBeEnabled()
  })

  it('disables move on a join and says why', () => {
    draw(JOINED_GRAPH, fannedRun())
    fireEvent.contextMenu(row('merge'))
    expect(screen.getByTestId('graph-menu-move')).toBeDisabled()
    expect(screen.getByTestId('graph-menu-refusal')).toHaveTextContent(
      'a task cannot be moved into a join',
    )
  })

  it('refuses the move for the reason T024c refuses it', () => {
    // The same rule the API answers `409 conflict` with (04 §Fan-in).
    const join = graphNode({ name: 'merge', generation: 3, join: true })
    expect(moveRefusal(join, 703)).toBe('a task cannot be moved into a join')
    expect(moveRefusal(graphNode({ name: 'qa', generation: 2 }), undefined)).toBe(
      'this run has no attempt to move',
    )
  })

  it('closes on esc', () => {
    draw()
    fireEvent.contextMenu(row('engineering'))
    expect(screen.getByTestId('graph-menu')).toBeInTheDocument()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByTestId('graph-menu')).toBeNull()
  })

  it('posts the rerun and reports the attempt it made', async () => {
    const urls = stubFetch({ task_id: 812 })
    draw()
    fireEvent.contextMenu(row('review'))
    fireEvent.click(screen.getByTestId('graph-menu-rerun'))

    await vi.waitFor(() => {
      expect(screen.getByTestId('graph-notice')).toHaveTextContent(
        'rerunning review · task 812',
      )
    })
    expect(urls.some((url) => url.endsWith(`/api/runs/${GRAPH_RUN}/rerun`))).toBe(true)
  })

  it('posts the move against the focused attempt', async () => {
    const urls = stubFetch({ task_id: 813 })
    draw()
    fireEvent.contextMenu(row('qa'))
    fireEvent.click(screen.getByTestId('graph-menu-move'))

    await vi.waitFor(() => {
      expect(screen.getByTestId('graph-notice')).toHaveTextContent('moved to qa · task 813')
    })
    expect(urls.some((url) => url.endsWith('/api/tasks/704/move'))).toBe(true)
  })

  it('says what a refused action said', async () => {
    stubFetch({ error: 'a task cannot be moved into a join', code: 'conflict' }, 409)
    draw()
    fireEvent.contextMenu(row('qa'))
    fireEvent.click(screen.getByTestId('graph-menu-move'))

    await vi.waitFor(() => {
      expect(screen.getByTestId('graph-notice')).toHaveTextContent(
        'a task cannot be moved into a join',
      )
    })
  })
})

/* -------------------------------------------------------------------- */
/* The states with nothing to draw                                       */
/* -------------------------------------------------------------------- */

describe('the states with no graph', () => {
  it('says which selection it is waiting for', () => {
    draw(null, null, { runId: undefined })
    expect(screen.getByTestId('pane-placeholder')).toHaveTextContent(
      'select a run to see its graph',
    )
    expect(screen.queryAllByTestId('graph-row')).toHaveLength(0)
  })

  it('names the refusal for a workflow this server does not have', async () => {
    stubFetch({ error: 'no workflow named feature_build', code: 'unknown_workflow' }, 404)
    draw(null, linearRun())

    await vi.waitFor(() => {
      expect(screen.getByTestId('pane-placeholder')).toHaveTextContent(
        'no workflow named feature_build',
      )
    })
  })

  it('omits the SOURCE line when the source is not available', () => {
    draw(LINEAR_GRAPH, linearRun(), { source: { file: undefined } })
    expect(screen.queryByTestId('graph-source')).toBeNull()
    expect(screen.getAllByTestId('graph-row')).not.toHaveLength(0)
  })
})

/**
 * The graph pane: where the canvas puts each node, which arrow it draws
 * between them, the chips a fan-out gives a node, and what the detail
 * line says.
 *
 * Three fixtures, which are the three shapes a run can have: linear with
 * a loop-back, a fan-out that never closes, and the same fan-out closed
 * by a join. Between them they cover every rule the canvas has — a rank
 * per generation, a node drawn **once** however many branches it ran in,
 * a join drawn with `⋈` and counting its arrivals, and a back edge that
 * leaves and arrives on the right.
 *
 * Four things this suite is deliberately strict about:
 *
 * - **the rank order is the route's.** `GET /api/runs/{id}/graph` sends
 *   the nodes in generation order and, within a generation, in
 *   declaration order (08), and {@link graphLayout} ranks and spreads
 *   them in exactly that order. Nothing sorts to reduce crossings.
 * - **a fan-out never duplicates a node.** Two branches of one fan-out
 *   are two *chips* on one card (D206 (2)), because the wire's edges
 *   name nodes and a second card would leave the arrows ambiguous.
 * - **`k of n arrived` is the join's, and only while a fan-out is
 *   open.** It comes from `arrivals`, which the server computes; nothing
 *   here counts branches.
 * - **nothing is zero-filled.** A node no agent measured shows what was
 *   measured and no more, and an idle node's detail line is absent
 *   rather than `0 · 0s` (01 §Real data only).
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createAppQueryClient } from '../../api/client'
import {
  getGraphApiRunsRunIdGraphGetQueryKey,
  getRunApiRunsRunIdGetQueryKey,
  getSourceApiWorkflowsNameSourceGetQueryKey,
} from '../../api/gen/@tanstack/react-query.gen'
import type { GraphOut, RunDetail } from '../../api/gen/types.gen'
import { narrowViewport, wideViewport } from '../../lib/__tests__/fixtures'
import {
  BRANCH_ROW,
  COLUMN_GAP,
  GraphCanvas,
  NODE_HEIGHT,
  NODE_WIDTH,
  RANK_GAP,
  UNTAKEN_CLASS,
  branchState,
  graphLayout,
  legendRows,
  moveRefusal,
  nodeDetail,
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
      <GraphCanvas
        runId={runId}
        taskId={options.taskId}
        onOpenNode={options.onOpenNode}
        onOpenLibrary={options.onOpenLibrary}
      />
    </QueryClientProvider>,
  )
}

/** The cards in the order they are drawn. */
function cards() {
  return screen.getAllByTestId('graph-row')
}

/** The node names in the order they are drawn. */
function names() {
  return cards().map((card) => card.getAttribute('data-node'))
}

/** The card for one node, by name. */
function card(node: string): HTMLElement {
  const found = cards().find((element) => element.getAttribute('data-node') === node)
  if (found === undefined) throw new Error(`no card for ${node}`)
  return found
}

/** The detail line of a card, or `null` when it draws none. */
function detailOf(element: HTMLElement): string | null {
  return element.querySelector('[data-testid="graph-detail"]')?.textContent ?? null
}

/** The branch chips of one node's card, in the order drawn. */
function chips(node: string): HTMLElement[] {
  return [...card(node).querySelectorAll<HTMLElement>('[data-testid="graph-branch"]')]
}

/** The layout of one fixture at {@link NOW}. */
function layout(graph: GraphOut, detail: RunDetail | null = null) {
  return graphLayout(graph, detail?.tasks, NOW)
}

/** One laid-out node, by name. */
function placed(graph: GraphOut, name: string, detail: RunDetail | null = null) {
  const node = layout(graph, detail).nodes.find((entry) => entry.id === name)
  if (node === undefined) throw new Error(`no node for ${name}`)
  return node
}

/** One laid-out edge, by the id `graph.ts` gives it. */
function edge(graph: GraphOut, id: string) {
  const found = layout(graph).edges.find((entry) => entry.id === id)
  if (found === undefined) throw new Error(`no edge for ${id}`)
  return found
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(NOW)
  queryClient = createAppQueryClient()
  // What is seeded is kept: nothing here refetches.
  queryClient.setDefaultOptions({ queries: { retry: false, staleTime: Infinity } })
})

afterEach(() => {
  wideViewport()
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

/* -------------------------------------------------------------------- */
/* The ranks                                                             */
/* -------------------------------------------------------------------- */

describe('the ranks the layout puts the nodes in', () => {
  it('draws a linear graph as one centred column, in the route’s order', () => {
    draw()
    expect(names()).toEqual(['prompt', 'engineering', 'review', 'qa', 'git'])

    const column = layout(LINEAR_GRAPH).nodes
    expect(column.map((node) => node.position.x)).toEqual([0, 0, 0, 0, 0])
    expect(column.map((node) => node.position.y)).toEqual(
      column.map((_, index) => index * (NODE_HEIGHT + RANK_GAP)),
    )
  })

  it('spreads one generation across a rank, centred, in declaration order', () => {
    const graph: GraphOut = {
      nodes: [
        graphNode({ name: 'plan', generation: 0 }),
        graphNode({ name: 'left', generation: 1 }),
        graphNode({ name: 'right', generation: 1 }),
      ],
      edges: [],
    }
    const pitch = NODE_WIDTH + COLUMN_GAP
    expect(placed(graph, 'left').position).toEqual({ x: -pitch / 2, y: NODE_HEIGHT + RANK_GAP })
    expect(placed(graph, 'right').position).toEqual({ x: pitch / 2, y: NODE_HEIGHT + RANK_GAP })
    expect(placed(graph, 'plan').position).toEqual({ x: 0, y: 0 })
  })

  it('leaves no empty band where a workflow skips a generation', () => {
    const graph: GraphOut = {
      nodes: [
        graphNode({ name: 'first', generation: 0 }),
        graphNode({ name: 'later', generation: 7 }),
      ],
      edges: [],
    }
    expect(placed(graph, 'later').position.y).toBe(NODE_HEIGHT + RANK_GAP)
  })

  it('gives every node an explicit width and height, so nothing is measured', () => {
    for (const node of layout(LINEAR_GRAPH).nodes) {
      expect(node.width).toBe(NODE_WIDTH)
      expect(node.height).toBe(NODE_HEIGHT)
      expect(node.type).toBe('athanore')
    }
  })

  it('makes a node that draws chips one chip row taller', () => {
    const fanned = placed(FANOUT_GRAPH, 'render', fannedRun())
    expect(fanned.height).toBe(NODE_HEIGHT + BRANCH_ROW)
    expect(placed(FANOUT_GRAPH, 'plan', fannedRun()).height).toBe(NODE_HEIGHT)
    // The rank below it starts under the taller card, not through it.
    expect(placed(FANOUT_GRAPH, 'report', fannedRun()).position.y).toBe(
      NODE_HEIGHT + RANK_GAP + NODE_HEIGHT + BRANCH_ROW + RANK_GAP,
    )
  })
})

/* -------------------------------------------------------------------- */
/* The edges                                                             */
/* -------------------------------------------------------------------- */

describe('the edges the layout draws', () => {
  it('runs a forward edge down the ranks, bottom to top', () => {
    const forward = edge(LINEAR_GRAPH, 'forward:prompt→engineering')
    expect(forward.sourceHandle).toBe('bottom')
    expect(forward.targetHandle).toBe('top')
    expect(forward.label).toBeUndefined()
    expect(forward.type).toBe('smoothstep')
  })

  it('bows a back edge out to the right, and labels it `loop`', () => {
    const back = edge(LINEAR_GRAPH, 'back:review→engineering')
    expect(back.sourceHandle).toBe('right-source')
    expect(back.targetHandle).toBe('right-target')
    expect(back.label).toBe('loop')
    expect(back.pathOptions).toEqual({ borderRadius: 12, offset: 24 })
  })

  it('draws a join edge exactly as a forward one', () => {
    // The `⋈` glyph on the target and the EDGES aside already say the
    // node is a fan-in; a third geometry would be a third notation.
    const join = edge(JOINED_GRAPH, 'join:report→merge')
    expect(join.sourceHandle).toBe('bottom')
    expect(join.targetHandle).toBe('top')
    expect(join.label).toBeUndefined()
  })

  it('labels an arrow this run took more than once', () => {
    expect(edge(FANOUT_GRAPH, 'forward:plan→render').label).toBe('×2')
  })

  it('marks an arrow this run never took', () => {
    const untaken = edge(LINEAR_GRAPH, 'forward:review→qa')
    expect(untaken.className).toBe(UNTAKEN_CLASS)
    expect(edge(LINEAR_GRAPH, 'forward:prompt→engineering').className).toBeUndefined()
    // A loop the run has not taken is still a loop, and still labelled.
    expect(edge(LINEAR_GRAPH, 'back:qa→engineering').label).toBe('loop')
  })

  it('drops an arrow naming a node this response does not carry', () => {
    const built = graphLayout(
      {
        nodes: [graphNode({ name: 'only', generation: 0 })],
        edges: [{ from: 'gone', to: 'only', kind: 'back', traversed: 1 }],
      },
      [],
      NOW,
    )
    expect(built.nodes).toHaveLength(1)
    expect(built.edges).toEqual([])
  })
})

/* -------------------------------------------------------------------- */
/* The branch chips                                                      */
/* -------------------------------------------------------------------- */

describe('the chips a fan-out gives a node', () => {
  it('draws the node once, with one chip per branch', () => {
    // The rail this replaced drew `render` twice. A canvas cannot: the
    // wire's edges name nodes, so a second card would leave every arrow
    // into and out of `render` ambiguous (D206 (2)).
    draw(FANOUT_GRAPH, fannedRun())
    expect(names()).toEqual(['plan', 'render', 'report'])
    expect(chips('render')).toHaveLength(2)
    expect(card('render').getAttribute('data-branches')).toBe('2')
  })

  it('keys the chips by the fan-out and the branch, not the fan-out alone', () => {
    draw(FANOUT_GRAPH, fannedRun())
    expect(chips('render').map((chip) => chip.getAttribute('data-branch'))).toEqual([
      '601:0',
      '601:1',
    ])
  })

  it('pairs a branch’s chips by their frames, not by their position', () => {
    // `report`'s entries arrive in the opposite order to `render`'s, so
    // a renderer that keyed by position would give branch 2's chip
    // branch 1's tag. The key is the branch-frame stack on the attempts.
    draw(FANOUT_GRAPH, fannedRun())
    expect(chips('report').map((chip) => chip.getAttribute('data-branch'))).toEqual([
      '601:0',
      '601:1',
    ])
    expect(chips('report').map((chip) => chip.getAttribute('title'))).toEqual([
      'branch 1 of 2 · alpha · from task 601',
      'branch 2 of 2 · beta · from task 601',
    ])
  })

  it('falls back to the position when the attempts have not arrived', () => {
    // `GraphBranch` alone cannot tell two branches of one fan-out apart
    // (08 §Graph semantics), so with no run detail a chip says which
    // branch of the entry list it is and no more.
    draw(FANOUT_GRAPH, null)
    expect(chips('render').map((chip) => chip.textContent)).toEqual(['#1', '#2'])
    expect(chips('render').map((chip) => chip.getAttribute('title'))).toEqual([
      'branch 1 · from task 601',
      'branch 2 · from task 601',
    ])
  })

  it('gives each chip its own branch’s state, not the node’s', () => {
    // `render` is `in_progress` as a node while one of its two branches
    // is running and the other is done: two chips in the node's own
    // colour would each claim to be the running one.
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

    expect(chips('render').map((chip) => chip.getAttribute('data-state'))).toEqual([
      'done',
      'in_progress',
    ])
    expect(card('render').getAttribute('data-state')).toBe('in_progress')
  })

  it('reads 08’s precedence over one branch’s attempts', () => {
    const attempt = (status: string) =>
      ({ status }) as unknown as Parameters<typeof branchState>[0][number]
    // A failed attempt with a retry queued reports `ready` (08).
    expect(branchState([attempt('failed'), attempt('ready')])).toBe('ready')
    expect(branchState([attempt('done'), attempt('in_progress')])).toBe('in_progress')
    expect(branchState([])).toBe('idle')
  })

  it('draws no chip on a node reached by a single path, or on a join', () => {
    draw(JOINED_GRAPH, fannedRun())
    expect(chips('plan')).toHaveLength(0)
    expect(chips('merge')).toHaveLength(0)
    expect(card('plan').getAttribute('data-branches')).toBeNull()
  })
})

/* -------------------------------------------------------------------- */
/* The card                                                              */
/* -------------------------------------------------------------------- */

describe('the card one node draws', () => {
  it('marks done, active, waiting and idle nodes', () => {
    draw()
    const glyph = (node: string) =>
      card(node).querySelector('[data-testid="graph-glyph"]')?.textContent
    expect(glyph('prompt')).toBe('✓')
    expect(glyph('engineering')).toBe('●')
    expect(glyph('review')).toBe('·')
    expect(glyph('qa')).toBe('·')
  })

  it('marks a join with ⋈ wherever its state is', () => {
    draw(JOINED_GRAPH, fannedRun())
    expect(card('merge').querySelector('[data-testid="graph-glyph"]')?.textContent).toBe(
      '⋈',
    )
  })

  it('pulses the node in progress and nothing else', () => {
    draw()
    const pulsing = screen
      .getAllByTestId('graph-glyph')
      .filter((glyph) => glyph.className.includes('animate-ath-pulse'))
    expect(pulsing).toHaveLength(1)
    expect(card('engineering')).toContainElement(pulsing[0] ?? null)
  })

  it('carries the node and its state as data attributes', () => {
    draw()
    expect(card('engineering').getAttribute('data-node')).toBe('engineering')
    expect(card('engineering').getAttribute('data-state')).toBe('in_progress')
    expect(card('qa').getAttribute('data-state')).toBe('idle')
  })
})

describe('the detail line', () => {
  it('shows tokens · duration for what a node has spent', () => {
    draw()
    expect(detailOf(card('prompt'))).toBe('18,204 · 9s')
  })

  it('shows attempt n · elapsed while a node is in progress', () => {
    draw()
    // Attempt 2 was claimed at 09:00:00 and the clock is at 09:01:45.
    expect(detailOf(card('engineering'))).toBe('attempt 2 · 105s')
  })

  it('shows waiting for a node parked on a request', () => {
    draw()
    expect(detailOf(card('review'))).toBe('waiting')
  })

  it('shows k of n arrived on a join with a fan-out still open', () => {
    draw(JOINED_GRAPH, fannedRun())
    expect(detailOf(card('merge'))).toBe('1 of 2 arrived')
  })

  it('sums every attempt of a node the fan-out ran more than once', () => {
    // The card is the node, so its line is the node's: branch 1 spent
    // 4,000 tokens over 20 s and branch 2 spent 9,000 over 40 s. Which
    // branch spent which is the chips' business, not this line's.
    draw(FANOUT_GRAPH, fannedRun())
    expect(detailOf(card('render'))).toBe('13,000 · 60s')
  })

  it('says nothing at all about a node the run has not reached', () => {
    draw()
    expect(detailOf(card('qa'))).toBeNull()
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
/* The canvas's own controls                                             */
/* -------------------------------------------------------------------- */

describe('panning and zooming', () => {
  it('offers zoom and fit as real buttons above the breakpoint', () => {
    draw()
    expect(screen.getByTestId('rf__controls')).toBeInTheDocument()
  })

  it('is a fitted picture below it, with no controls to reach for', () => {
    // 21 §Narrow layout: there is no wheel and no room for a control
    // strip on a phone, and the EDGES block underneath carries the
    // detail instead.
    narrowViewport()
    draw()
    expect(screen.queryByTestId('rf__controls')).toBeNull()
    expect(screen.getAllByTestId('graph-legend-row')).not.toHaveLength(0)
    expect(cards()).not.toHaveLength(0)
  })
})

/* -------------------------------------------------------------------- */
/* Which of the two layouts the pane draws                               */
/* -------------------------------------------------------------------- */

/**
 * A `ResizeObserver` that reports what a test tells it to.
 *
 * `src/test-setup.ts` installs one that observes nothing, which is the
 * truth of jsdom — and it is why every other case in this file gets the
 * layout the viewport implies. These cases are about the other input:
 * the pane's own width, which in a browser is the viewport minus the run
 * list, minus the splitter, divided by the pane cycle.
 */
class MeasuringResizeObserver implements ResizeObserver {
  static width = 0
  static readonly live = new Set<MeasuringResizeObserver>()

  readonly callback: ResizeObserverCallback
  readonly targets: Element[] = []

  constructor(callback: ResizeObserverCallback) {
    this.callback = callback
  }

  observe(target: Element): void {
    MeasuringResizeObserver.live.add(this)
    this.targets.push(target)
    this.report()
  }

  unobserve(): void {}

  disconnect(): void {
    MeasuringResizeObserver.live.delete(this)
  }

  /**
   * The observed boxes, with their real elements.
   *
   * React Flow observes its own container through the same global, and
   * reads the element back out of the entry, so a stand-in that reported
   * a bare rectangle would break the library rather than the pane.
   */
  report(): void {
    this.callback(
      this.targets.map(
        (target) =>
          ({
            target,
            contentRect: { width: MeasuringResizeObserver.width },
          }) as ResizeObserverEntry,
      ),
      this,
    )
  }
}

/** Draw the pane in a box `width` px wide, whatever the window says. */
function drawInPane(width: number) {
  MeasuringResizeObserver.width = width
  const real = globalThis.ResizeObserver
  globalThis.ResizeObserver =
    MeasuringResizeObserver as unknown as typeof ResizeObserver
  try {
    act(() => {
      draw()
    })
  } finally {
    globalThis.ResizeObserver = real
  }
}

/** `stacked` or `split`, as the pane itself reports it. */
function layoutDrawn(): string | null {
  return screen.getByTestId('graph-frame').getAttribute('data-layout')
}

describe('the layout follows the pane, not the window', () => {
  afterEach(() => {
    MeasuringResizeObserver.live.clear()
  })

  it('stacks a pane too narrow for both columns, above the breakpoint', () => {
    // A 900 px window leaves the pane about this much once the run list
    // and the splitter have taken their share. The CSS breakpoint calls
    // that a desktop; the pane is not one (D206 (10)).
    drawInPane(460)

    expect(layoutDrawn()).toBe('stacked')
    // Which is the phone's column order — the canvas, then the EDGES
    // block underneath — but not the phone's canvas: there is a pointer
    // here, so the controls stay and the fit keeps the interaction
    // floor rather than shrinking the graph to fit (D206 (11)).
    expect(screen.getByTestId('rf__controls')).toBeInTheDocument()
    expect(cards()).not.toHaveLength(0)
    expect(screen.getAllByTestId('graph-legend-row')).not.toHaveLength(0)
  })

  it('drops the controls only where there is no gesture to use them', () => {
    // The phone: stacked *and* narrow. This is the one layout whose
    // picture has to be the whole picture, because nothing on screen
    // can move it (D206 (7)).
    narrowViewport()
    drawInPane(320)

    expect(layoutDrawn()).toBe('stacked')
    expect(screen.queryByTestId('rf__controls')).toBeNull()
  })

  it('splits a pane with room for both, below the breakpoint', () => {
    // The other direction, and the reason this is measured rather than
    // queried: `b` hides the run list, which hands the pane the window.
    narrowViewport()
    drawInPane(700)

    expect(layoutDrawn()).toBe('split')
    expect(screen.getByTestId('rf__controls')).toBeInTheDocument()
  })

  it('splits at the width the two columns need, and stacks a pixel under it', () => {
    // 320 (the canvas basis) + 26 (the gutter) + 210 (the aside's).
    drawInPane(556)
    expect(layoutDrawn()).toBe('split')

    cleanup()
    drawInPane(555)
    expect(layoutDrawn()).toBe('stacked')
  })

  it('falls back to the window until the pane has been measured', () => {
    // The first paint happens before the observer's first callback, and
    // a hidden pane never reports a width at all.
    narrowViewport()
    draw()
    expect(layoutDrawn()).toBe('stacked')

    cleanup()
    wideViewport()
    draw()
    expect(layoutDrawn()).toBe('split')
  })
})

/* -------------------------------------------------------------------- */
/* Clicking and right-clicking                                           */
/* -------------------------------------------------------------------- */

describe('clicking a node', () => {
  it('jumps to the log pane filtered to that node', () => {
    const onOpenNode = vi.fn()
    draw(LINEAR_GRAPH, linearRun(), { onOpenNode })
    fireEvent.click(card('review'))
    expect(onOpenNode).toHaveBeenCalledWith('review')
  })
})

describe('the right-click menu', () => {
  it('offers rerun and move for the node it was opened on', () => {
    draw()
    fireEvent.contextMenu(card('engineering'))
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
    fireEvent.contextMenu(card('merge'))
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
    fireEvent.contextMenu(card('engineering'))
    expect(screen.getByTestId('graph-menu')).toBeInTheDocument()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByTestId('graph-menu')).toBeNull()
  })

  it('closes on a click of the canvas behind it', () => {
    // A click outside is the other half of 10 §Overlays' rule, and on a
    // canvas the outside is the pane the nodes sit on.
    const { container } = draw()
    fireEvent.contextMenu(card('engineering'))
    const pane = container.querySelector('.react-flow__pane')
    expect(pane).not.toBeNull()
    fireEvent.click(pane as Element)
    expect(screen.queryByTestId('graph-menu')).toBeNull()
  })

  it('posts the rerun and reports the attempt it made', async () => {
    const urls = stubFetch({ task_id: 812 })
    draw()
    fireEvent.contextMenu(card('review'))
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
    fireEvent.contextMenu(card('qa'))
    fireEvent.click(screen.getByTestId('graph-menu-move'))

    await vi.waitFor(() => {
      expect(screen.getByTestId('graph-notice')).toHaveTextContent('moved to qa · task 813')
    })
    expect(urls.some((url) => url.endsWith('/api/tasks/704/move'))).toBe(true)
  })

  it('says what a refused action said', async () => {
    stubFetch({ error: 'a task cannot be moved into a join', code: 'conflict' }, 409)
    draw()
    fireEvent.contextMenu(card('qa'))
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

  it('draws nothing but the EDGES note for a workflow of one node', () => {
    const solo: GraphOut = {
      nodes: [graphNode({ name: 'only', generation: 0 })],
      edges: [],
    }
    draw(solo, linearRun())
    expect(names()).toEqual(['only'])
    expect(screen.getByText('this workflow has one node')).toBeInTheDocument()
  })
})

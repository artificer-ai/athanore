/**
 * The graph pane: the run's shape as a React Flow canvas
 * (`docs/v1/10-frontend.md` §Graph pane and §Panes item 5, over `GET
 * /api/runs/{id}/graph` of `docs/v1/08-api.md` §Graph semantics, and the
 * mock's `isGraph` block in `docs/v1/design/Athanore.dc.html`).
 *
 * `WORKFLOW GRAPH · <workflow>` with the active / done / failed legend,
 * then one card per node — a glyph, the name, a detail line, and a chip
 * per branch of the fan-out it ran in — laid out in ranks by generation,
 * with the graph's own arrows drawn as edges: forward and join edges
 * down the ranks, back edges bowing out to the right with a `loop`
 * label. Beside the canvas: the EDGES block, the SOURCE path and `open
 * definition`.
 *
 * **A canvas, and a graph library** (15, D206, superseding D32). The
 * rail list this replaced drew the arrows as `▼` connectors and a
 * right-hand rail of 1 px spans, which a pipeline with one loop-back can
 * carry and a fan-out cannot: a list has no arrows, so a branch could be
 * a sub-list, and on a canvas it cannot. The operator asked for the
 * canvas and 10 §Graph pane now specifies it.
 *
 * **The shape is `./graph.ts`.** Where every card sits, how tall it is,
 * which chips it draws, which handles an edge leaves and arrives on and
 * what the detail line says are all decided there, without a DOM; this
 * file paints them. Nothing here measures a *node*: every node carries
 * an explicit `width` and `height`, which is what React Flow calls
 * measured (D206 (4)). The one box this file does measure is the pane
 * itself, because which of the two layouts it draws is a fact about how
 * much room the pane has and not about how wide the window is (D206
 * (10)).
 *
 * **Three requests, all of them the app's own cache entries.** The graph
 * is the generated query, so it is the entry `run.*` and `task.*`
 * invalidate (10 §Realtime and caching) and the one `usePanes` already
 * reads for `node`-slot liveness — one entry, so the pane and the pane
 * cycle cannot disagree about the shape of the run. `GET /api/runs/{id}`
 * is the same shared entry the overview and the agent pane read, and it
 * is where the detail line's tokens and durations come from: the graph
 * route carries a node's *state*, and what its attempts spent is a fact
 * about the attempts. `GET /api/workflows/{name}/source` is the SOURCE
 * path, which is the only place the wire carries the file a workflow is
 * defined in — the same entry the library overlay reads, so opening it
 * costs nothing twice.
 *
 * **Clicking is the log, right-clicking is the two node operations.** 10
 * §Graph pane: "Clicking a node jumps to the log pane filtered to that
 * node; right-click offers rerun here / move task here (move is disabled
 * for join nodes)." The move item is disabled rather than hidden, and it
 * says why, because the refusal is the API's own `409 conflict` (08
 * §Tasks, 04 §Fan-in) and an operator who reaches for it should learn
 * the rule rather than wonder where the item went.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Controls,
  Handle,
  Position,
  ReactFlow,
  type NodeProps,
} from '@xyflow/react'
import { memo, useEffect, useState } from 'react'

import {
  getGraphApiRunsRunIdGraphGetOptions,
  getGraphApiRunsRunIdGraphGetQueryKey,
  getRunApiRunsRunIdGetQueryKey,
  getSourceApiWorkflowsNameSourceGetOptions,
  moveTaskApiTasksTaskIdMovePostMutation,
  rerunNodeApiRunsRunIdRerunPostMutation,
} from '../../api/gen/@tanstack/react-query.gen'
import type { GraphNode } from '../../api/gen/types.gen'
import { toneClass, tonePulses, useNow } from '../../components/RunList'
import { actionError } from '../../lib/errors'
import { useElementWidth } from '../../lib/useElementWidth'
import { useIsNarrow } from '../../lib/useIsNarrow'
import { cn } from '../../lib/utils'
import { PlaceholderCard } from './cards'
import {
  HANDLES,
  LEGEND_GLOSS,
  graphLayout,
  legendRows,
  moveRefusal,
  type GraphFlowNode,
  type LegendKind,
} from './graph'
import { useRunDetail } from './run'
import { focusedTask } from './stream'

/** The mock's header separator: a neutral-800 pipe between the parts. */
function Bar() {
  return <span className="text-[var(--color-neutral-800)]">│</span>
}

/**
 * `GET /api/runs/{id}/graph`: the run's shape, with per-node state.
 *
 * The generated query, so its key is the one the invalidation table
 * refreshes on `run.*` and `task.*` (10 §Realtime and caching) and the
 * one `usePanes` reads for `node`-slot liveness — one cache entry, so
 * the pane cycle and this pane cannot disagree about which nodes are
 * live. `queryFn` is put back explicitly for the reason `./run.ts`
 * gives.
 */
function useGraph(runId: string | undefined) {
  const { queryFn, ...options } = getGraphApiRunsRunIdGraphGetOptions({
    path: { run_id: runId ?? '' },
  })
  return useQuery({
    ...options,
    queryFn: queryFn!,
    enabled: runId !== undefined,
  })
}

/**
 * `GET /api/workflows/{name}/source`: the file the workflow is defined
 * in, for the SOURCE line.
 *
 * The response carries the module's whole text as well, which this pane
 * does not draw — but it is the entry the library overlay reads, and
 * asking for it here is what makes `open definition` open on a source
 * that is already in hand. `queryFn` is put back explicitly for the
 * reason `./run.ts` gives.
 */
function useSource(workflow: string | undefined) {
  const { queryFn, ...options } = getSourceApiWorkflowsNameSourceGetOptions({
    path: { name: workflow ?? '' },
  })
  return useQuery({
    ...options,
    queryFn: queryFn!,
    enabled: workflow !== undefined,
    // A workflow whose source Python cannot produce is a 404 (08
    // §Workflows), which is an answer and not a fault: retrying it would
    // be three requests for a line this pane simply omits.
    retry: false,
  })
}

/** One dot of the header legend: `● active`, `● done`, `● failed`. */
function LegendDot({ colour, label }: { colour: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-[5px] whitespace-nowrap">
      <span
        aria-hidden="true"
        className="inline-block size-[6px] rounded-full"
        style={{ background: colour }}
      />
      {label}
    </span>
  )
}

/**
 * The four anchor points an edge of `./graph.ts` names.
 *
 * All of them are 1 px, transparent and `aria-hidden`, and none is
 * connectable: the workflow is defined in Python and drawn here, so a
 * handle is where an arrow meets a card and nothing an operator can take
 * hold of. The pair on the right is what a back edge leaves and arrives
 * on, which is how a loop keeps the mock's right-hand idiom (D206 (5)).
 */
function Anchors() {
  return (
    <>
      <Handle
        type="target"
        id={HANDLES.top}
        position={Position.Top}
        isConnectable={false}
        aria-hidden="true"
        className="graph-handle"
      />
      <Handle
        type="source"
        id={HANDLES.bottom}
        position={Position.Bottom}
        isConnectable={false}
        aria-hidden="true"
        className="graph-handle"
      />
      <Handle
        type="source"
        id={HANDLES.loopOut}
        position={Position.Right}
        isConnectable={false}
        aria-hidden="true"
        className="graph-handle"
      />
      <Handle
        type="target"
        id={HANDLES.loopIn}
        position={Position.Right}
        isConnectable={false}
        aria-hidden="true"
        className="graph-handle"
      />
    </>
  )
}

/**
 * One node's card: the glyph, the name, the detail line and the chips of
 * the fan-out it ran in.
 *
 * The card's own `<button>` is the single tab stop and the thing `⏎`
 * activates — React Flow's node wrapper takes no `tabIndex` of its own,
 * because the canvas sets `nodesFocusable={false}` — and the click and
 * the right-click are handled by the canvas's `onNodeClick` /
 * `onNodeContextMenu`, which the button's own events bubble to.
 *
 * **The test ids are the rail's on purpose** (D206 (9)): `graph-row`,
 * `graph-detail`, `data-node` and `data-state` mean exactly what they
 * meant, and `web/e2e/support/fixtures.ts`, `run.spec.ts`, `a11y.spec.ts`
 * and `App.test.tsx` all reach for them.
 */
const GraphNodeCard = memo(function GraphNodeCard({
  data,
}: NodeProps<GraphFlowNode>) {
  const active = data.state === 'in_progress'

  return (
    <>
      <Anchors />
      <button
        type="button"
        data-testid="graph-row"
        data-node={data.node.name}
        data-state={data.state}
        {...(data.branches.length === 0
          ? {}
          : { 'data-branches': String(data.branches.length) })}
        className={cn(
          'text-row flex h-full w-full cursor-pointer flex-col justify-center gap-[2px] rounded-lg border px-[10px] py-[6px] text-left text-[var(--color-neutral-300)]',
          active
            ? 'border-[var(--color-accent-600)] bg-[color-mix(in_srgb,var(--color-accent)_12%,var(--color-surface))] shadow-[0_0_0_1px_color-mix(in_srgb,var(--color-accent)_30%,transparent)]'
            : 'border-[var(--color-neutral-800)] bg-card',
          'hover:border-[var(--color-accent-500)]',
        )}
      >
        <span className="flex items-center gap-[8px]">
          <span
            data-testid="graph-glyph"
            aria-hidden="true"
            className={cn(
              'w-[14px] flex-none',
              toneClass(data.tone),
              tonePulses(data.tone) && 'animate-ath-pulse',
            )}
          >
            {data.glyph}
          </span>
          <span className="min-w-0 flex-1 truncate">{data.node.name}</span>
        </span>
        {data.detail !== '' && (
          <span
            data-testid="graph-detail"
            className="text-hint truncate pl-[22px] text-[var(--color-neutral-500)]"
          >
            {data.detail}
          </span>
        )}
        {data.branches.length > 0 && (
          <span className="flex flex-wrap items-center gap-[4px] pl-[22px]">
            {data.branches.map((chip, position) => (
              <span
                key={`${chip.tag}/${String(position)}`}
                data-testid="graph-branch"
                data-branch={chip.tag}
                data-state={chip.state}
                title={chip.label}
                className={cn(
                  'text-hint rounded border border-[var(--color-neutral-800)] px-[4px] leading-[14px]',
                  toneClass(chip.tone),
                )}
              >
                {chip.short}
              </span>
            ))}
          </span>
        )}
      </button>
    </>
  )
})

/**
 * The one node kind the canvas draws, at module scope.
 *
 * React Flow re-mounts every node when the `nodeTypes` object changes
 * identity, so building this in the render would throw the cards away on
 * every tick of the elapsed clock.
 */
const NODE_TYPES = { athanore: GraphNodeCard }

/**
 * The narrowest pane that can hold the canvas and the EDGES block side by
 * side: the canvas's flex basis (320 px, a 208 px card and room to
 * breathe), the 26 px gutter, and the aside's (210 px). D206 (10).
 *
 * Below it the two columns become one, because neither can shrink any
 * further and be worth drawing — a 118 px canvas is half a card, and the
 * cards do not scroll into reach, they are clipped. This is a width of
 * the *pane*, not of the window: at Tailwind's `md` with the run list
 * shown the pane is around 330 px, which is why the breakpoint alone
 * cannot answer this.
 */
const SPLIT_WIDTH = 556

/** What the right-click menu is open on, and where it was opened. */
type Menu = { node: GraphNode; x: number; y: number }

/**
 * The two node operations of 10 §Graph pane, at the pointer.
 *
 * Hand-rolled rather than a Radix `ContextMenu`: the mock has no menu to
 * match, this one has two items and no submenu or typeahead, and a
 * portalled menu would put the pane's only mutations behind a component
 * whose focus machinery the pane does not otherwise need (15, D167).
 * `esc` and a click outside close it, which is the behaviour 10
 * §Overlays gives everything that floats.
 */
function NodeMenu({
  menu,
  taskId,
  busy,
  onRerun,
  onMove,
  onClose,
}: {
  menu: Menu
  taskId: number | undefined
  busy: boolean
  onRerun: () => void
  onMove: () => void
  onClose: () => void
}) {
  const refusal = moveRefusal(menu.node, taskId)

  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    const away = () => {
      onClose()
    }
    document.addEventListener('keydown', key)
    document.addEventListener('pointerdown', away)
    return () => {
      document.removeEventListener('keydown', key)
      document.removeEventListener('pointerdown', away)
    }
  }, [onClose])

  return (
    <div
      role="menu"
      aria-label={`actions for ${menu.node.name}`}
      data-testid="graph-menu"
      data-node={menu.node.name}
      style={{ left: menu.x, top: menu.y }}
      // The listener that closes the menu is on the document, so the
      // menu stops the events of its own body from reaching it.
      onPointerDown={(event) => {
        event.stopPropagation()
      }}
      className="fixed z-50 min-w-[180px] rounded-lg border border-[var(--color-neutral-800)] bg-popover py-[4px] shadow-[var(--shadow-lg)]"
    >
      <p className="text-hint px-[10px] py-[3px] tracking-[0.1em] text-[var(--color-neutral-600)]">
        {menu.node.name}
      </p>
      <button
        type="button"
        role="menuitem"
        data-testid="graph-menu-rerun"
        disabled={busy}
        onClick={onRerun}
        className="text-row block w-full px-[10px] py-[4px] text-left text-[var(--color-neutral-300)] enabled:cursor-pointer enabled:hover:bg-[var(--color-neutral-900)] disabled:text-[var(--color-neutral-600)]"
      >
        rerun here
      </button>
      <button
        type="button"
        role="menuitem"
        data-testid="graph-menu-move"
        disabled={busy || refusal !== undefined}
        {...(refusal === undefined ? {} : { title: refusal })}
        onClick={onMove}
        className="text-row block w-full px-[10px] py-[4px] text-left text-[var(--color-neutral-300)] enabled:cursor-pointer enabled:hover:bg-[var(--color-neutral-900)] disabled:text-[var(--color-neutral-600)]"
      >
        move task {taskId === undefined ? '' : `${String(taskId)} `}here
      </button>
      {refusal !== undefined && (
        <p
          data-testid="graph-menu-refusal"
          className="text-hint px-[10px] pt-[2px] pb-[3px] text-[var(--color-neutral-600)]"
        >
          {refusal}
        </p>
      )}
    </div>
  )
}

/** The EDGES block, the SOURCE path, and `open definition`. */
function Aside({
  legend,
  file,
  onOpenLibrary,
}: {
  legend: ReturnType<typeof legendRows>
  file?: string | undefined
  onOpenLibrary: (() => void) | undefined
}) {
  return (
    <div className="min-w-0 max-w-[320px] flex-[1_1_210px] border-t border-[var(--color-neutral-900)] pt-[14px]">
      <p className="text-hint mb-[8px] tracking-[0.14em] text-[var(--color-neutral-500)]">
        EDGES
      </p>
      {legend.length === 0 ? (
        <p className="text-meta text-muted-foreground">this workflow has one node</p>
      ) : (
        <div className="flex flex-col gap-[5px]">
          {legend.map((row, index) => (
            <div
              key={`${row.kind}/${row.text}/${String(index)}`}
              data-testid="graph-legend-row"
              data-kind={row.kind}
              title={LEGEND_GLOSS[row.kind as LegendKind]}
              className="flex items-baseline gap-[8px]"
            >
              <span className="text-meta text-[var(--color-accent-400)]">{row.kind}</span>
              <span className="text-meta [overflow-wrap:anywhere] text-[var(--color-neutral-500)]">
                {row.text}
              </span>
            </div>
          ))}
        </div>
      )}

      {file !== undefined && (
        <>
          <p className="text-hint mt-[16px] mb-[8px] tracking-[0.14em] text-[var(--color-neutral-500)]">
            SOURCE
          </p>
          <p
            data-testid="graph-source"
            className="text-meta [overflow-wrap:anywhere] text-[var(--color-neutral-500)]"
          >
            {file}
          </p>
        </>
      )}

      {onOpenLibrary !== undefined && (
        <button
          type="button"
          data-testid="graph-open-definition"
          onClick={onOpenLibrary}
          className="text-meta mt-[10px] cursor-pointer rounded-lg border border-[var(--color-neutral-800)] px-[8px] py-[4px] text-[var(--color-neutral-400)] hover:border-[var(--color-accent-600)] hover:text-[var(--color-accent-200)]"
        >
          open definition
        </button>
      )}
    </div>
  )
}

/** A status line: what the pane is waiting for, or has nothing of. */
function Status({ children }: { children: string }) {
  return (
    <p className="text-row p-[12px_14px] text-muted-foreground" role="status">
      {children}
    </p>
  )
}

export function GraphCanvas({
  runId,
  taskId,
  onOpenNode,
  onOpenLibrary,
}: {
  /** The run in scope, from `?run=`. */
  runId: string | undefined
  /** The focused attempt, from `?task=`: what `move task here` moves. */
  taskId?: number | undefined
  /** Click a card: `?node=`, and the log pane (10 §Graph pane). */
  onOpenNode?: ((node: string) => void) | undefined
  /** `open definition`: the workflow library overlay (10 §Overlays). */
  onOpenLibrary?: (() => void) | undefined
}) {
  const detail = useRunDetail(runId)
  const workflow = detail?.workflow
  const { data: graph, isError, error } = useGraph(runId)
  const { data: source } = useSource(workflow)
  const queryClient = useQueryClient()

  // Which of the two layouts this pane draws is a question about the
  // *pane*, not the viewport: the run list, the splitter and the pane
  // cycle all take width off it, so a 900 px window leaves ~460 px here
  // and a 768 px one with the run list hidden leaves ~740 px. Until the
  // observer has answered, the viewport is the best guess available, and
  // it is the right one at both ends — a phone is stacked and a desktop
  // pane is not.
  const [measure, paneWidth] = useElementWidth()
  const narrow = useIsNarrow()
  const stacked = paneWidth === null ? narrow : paneWidth < SPLIT_WIDTH

  // The elapsed half of `attempt n · elapsed` is `now − started`, and the
  // finest unit it prints is a second — the same reason the run list's
  // AGE column carries a clock, and the same clock.
  const now = useNow()
  const layout = graphLayout(graph, detail?.tasks, now)
  const legend = legendRows(graph)

  const [menu, setMenu] = useState<Menu | null>(null)
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null)

  const focused = focusedTask(detail?.tasks, taskId)

  const refresh = () => {
    if (runId === undefined) return
    void queryClient.invalidateQueries({
      queryKey: getGraphApiRunsRunIdGraphGetQueryKey({ path: { run_id: runId } }),
    })
    void queryClient.invalidateQueries({
      queryKey: getRunApiRunsRunIdGetQueryKey({ path: { run_id: runId } }),
    })
  }

  const rerun = useMutation({
    ...rerunNodeApiRunsRunIdRerunPostMutation(),
    onSuccess: (data, variables) => {
      setNotice({
        ok: true,
        text: `rerunning ${variables.body.node} · task ${String(data.task_id)}`,
      })
      refresh()
    },
    onError: (failure) => {
      setNotice({ ok: false, text: actionError(failure, 'the node was not rerun') })
    },
  })

  const move = useMutation({
    ...moveTaskApiTasksTaskIdMovePostMutation(),
    onSuccess: (data, variables) => {
      setNotice({
        ok: true,
        text: `moved to ${variables.body.node} · task ${String(data.task_id)}`,
      })
      refresh()
    },
    onError: (failure) => {
      setNotice({ ok: false, text: actionError(failure, 'the task was not moved') })
    },
  })

  const busy = rerun.isPending || move.isPending

  const openMenu = (node: GraphNode, x: number, y: number) => {
    setNotice(null)
    setMenu({ node, x, y })
  }

  const runRerun = () => {
    if (menu === null || runId === undefined) return
    const node = menu.node.name
    setMenu(null)
    rerun.mutate({ path: { run_id: runId }, body: { node } })
  }

  const runMove = () => {
    if (menu === null || focused === undefined) return
    const node = menu.node.name
    setMenu(null)
    move.mutate({ path: { task_id: focused.id }, body: { node } })
  }

  return (
    <div data-testid="pane-graph" className="flex min-h-0 flex-1 flex-col">
      <div className="text-hint flex flex-none flex-wrap items-center gap-x-[10px] gap-y-[6px] border-b border-[var(--color-neutral-800)] px-[14px] py-[6px] tracking-[0.1em] text-muted-foreground">
        <span className="whitespace-nowrap">WORKFLOW GRAPH</span>
        {workflow !== undefined && (
          <>
            <Bar />
            <span
              data-testid="graph-workflow"
              className="whitespace-nowrap text-[var(--color-neutral-300)]"
            >
              {workflow}
            </span>
          </>
        )}
        <div className="flex-1" />
        <LegendDot colour="var(--color-accent)" label="active" />
        <LegendDot colour="var(--color-neutral-500)" label="done" />
        <LegendDot colour="var(--ath-status-fail)" label="failed" />
      </div>

      {/* Under the bar and outside the canvas: an action's result is not
          something an operator should have to pan back to. */}
      {notice !== null && (
        <p
          data-testid="graph-notice"
          role="status"
          className={cn(
            'text-hint flex-none px-[14px] pt-[8px]',
            notice.ok ? 'text-[var(--color-accent-300)]' : 'text-status-fail',
          )}
        >
          {notice.text}
        </p>
      )}

      {runId === undefined ? (
        <div className="p-[12px_14px]">
          <PlaceholderCard
            title="select a run to see its graph"
            detail="the graph is one run's history projected onto its workflow"
          />
        </div>
      ) : isError ? (
        // 404 `unknown_workflow` is the answer for a run whose workflow
        // this process does not have (08 §Graph semantics), and it is the
        // one refusal this pane must not draw as an empty graph.
        <div className="p-[12px_14px]">
          <PlaceholderCard
            title="this run's graph is not available here"
            detail={actionError(
              error,
              'this server has no workflow of that name registered',
            )}
          />
        </div>
      ) : graph === undefined ? (
        <Status>loading the graph…</Status>
      ) : (
        /* Wide enough for both columns, the canvas fills the pane and the
           aside scrolls beside it; stacked, the canvas is a fitted
           picture of fixed height with the EDGES block underneath, and
           the pane scrolls as one (21 §Narrow layout, D206 (10)). */
        <div
          ref={measure}
          data-testid="graph-frame"
          data-layout={stacked ? 'stacked' : 'split'}
          className={
            stacked
              ? 'flex min-h-0 flex-1 flex-col overflow-y-auto px-[14px] pb-[18px]'
              : 'flex min-h-0 flex-1 flex-row items-stretch gap-x-[26px] overflow-hidden px-[14px] pb-[18px]'
          }
        >
          <div
            className={
              stacked
                ? 'h-[320px] flex-none'
                : 'h-auto min-h-0 min-w-0 flex-[2_1_320px]'
            }
          >
            <ReactFlow<GraphFlowNode>
              /* `fitView` is solved once, when the nodes are first
                 measured, and a container that changes size afterwards
                 does not re-solve it. Both the run and the layout change
                 what the right fit is — the two layouts do not even share
                 a floor — so both are in the key. */
              key={`${runId ?? ''}/${stacked ? 'stacked' : 'split'}`}
              nodes={layout.nodes}
              edges={layout.edges}
              nodeTypes={NODE_TYPES}
              colorMode="dark"
              fitView
              /* The fit gets its own floor, because `getViewportForBounds`
                 clamps the zoom it solves to `fitViewOptions.minZoom ??
                 minZoom`. Stacked there is no pan, no pinch and no
                 controls, so a fit floored at the interaction floor
                 would put the top and bottom of a tall graph — eight ranks
                 is `examples/feature_build` — out of reach for good. The
                 picture shrinks instead (D206 (7)). */
              fitViewOptions={{
                padding: 0.15,
                maxZoom: 1,
                minZoom: stacked ? 0.05 : 0.4,
              }}
              minZoom={0.4}
              maxZoom={1.6}
              nodesDraggable={false}
              nodesConnectable={false}
              nodesFocusable={false}
              edgesFocusable={false}
              elementsSelectable={false}
              zoomOnScroll={false}
              zoomOnDoubleClick={false}
              preventScrolling={false}
              panOnDrag={!stacked}
              zoomOnPinch={!stacked}
              aria-label={
                workflow === undefined ? 'workflow graph' : `workflow graph for ${workflow}`
              }
              onNodeClick={(_, node) => {
                onOpenNode?.(node.id)
              }}
              onNodeContextMenu={(event, node) => {
                event.preventDefault()
                openMenu(node.data.node, event.clientX, event.clientY)
              }}
              onPaneClick={() => {
                setMenu(null)
              }}
            >
              {!stacked && <Controls showInteractive={false} position="bottom-left" />}
            </ReactFlow>
          </div>

          <div
            className={
              stacked
                ? 'flex flex-none flex-col'
                : 'flex min-w-0 max-w-[300px] flex-[1_1_210px] flex-col overflow-y-auto'
            }
          >
            <Aside
              legend={legend}
              {...(source?.file === undefined ? {} : { file: source.file })}
              onOpenLibrary={onOpenLibrary}
            />
          </div>
        </div>
      )}

      {menu !== null && (
        <NodeMenu
          menu={menu}
          taskId={focused?.id}
          busy={busy}
          onRerun={runRerun}
          onMove={runMove}
          onClose={() => {
            setMenu(null)
          }}
        />
      )}
    </div>
  )
}

/**
 * The graph pane: the run's shape as a vertical rail
 * (`docs/v1/10-frontend.md` §Graph pane and §Panes item 5, over `GET
 * /api/runs/{id}/graph` of `docs/v1/08-api.md` §Graph semantics, and the
 * mock's `isGraph` block in `docs/v1/design/Athanore.dc.html`).
 *
 * `WORKFLOW GRAPH · <workflow>` with the active / done / failed legend,
 * then one row per node — a glyph, the name, a detail column — with
 * `▼` connectors between them, the fan-out's branches as indented
 * sub-lists, `▲` from each sub-list into the join that closes it, and a
 * right-hand rail carrying the back edges with `◀` and a `loop` label.
 * Beside the rail: the EDGES block, the SOURCE path and `open
 * definition`.
 *
 * **No graph library and no canvas** (15, D32). The mock's pipeline is a
 * list of rows and a rail drawn with 1 px spans, and 10 fixes that as
 * the v1 renderer: "React Flow is **not** used… A canvas renderer is a
 * later seam." Every position on this page comes out of the row order
 * the API already sent.
 *
 * **The shape is `./graph.ts`.** Which rows there are, which sub-list
 * each is in, which rails cross which rows and what the detail column
 * says are all decided there, without a DOM; this file paints them.
 *
 * **Three requests, all of them the app's own cache entries.** The graph
 * is the generated query, so it is the entry `run.*` and `task.*`
 * invalidate (10 §Realtime and caching) and the one `usePanes` already
 * reads for `node`-slot liveness — one entry, so the pane and the pane
 * cycle cannot disagree about the shape of the run. `GET /api/runs/{id}`
 * is the same shared entry the overview and the agent pane read, and it
 * is where the detail column's tokens and durations come from: the
 * graph route carries a node's *state*, and what its attempts spent is a
 * fact about the attempts. `GET /api/workflows/{name}/source` is the
 * SOURCE path, which is the only place the wire carries the file a
 * workflow is defined in — the same entry the library overlay (T066c)
 * will read, so opening it costs nothing twice.
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
import { useEffect, useState } from 'react'

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
import { cn } from '../../lib/utils'
import { PlaceholderCard } from './cards'
import {
  LEGEND_GLOSS,
  branchLabel,
  branchTag,
  legendRows,
  moveRefusal,
  railRows,
  type LegendKind,
  type RailRow,
} from './graph'
import { useRunDetail } from './run'
import { focusedTask } from './stream'

/** How far a sub-list's rows are indented from the parent, in pixels. */
const INDENT_PX = 18

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

/** `▼` under a row, or `▲` where a sub-list arrives at its join. */
function Connector({ into }: { into: boolean }) {
  return (
    <div
      data-testid={into ? 'graph-into-join' : 'graph-connector'}
      className="ml-[12px] flex w-[28px] flex-col items-center"
    >
      <span className="block h-[16px] w-px bg-[var(--color-neutral-700)]" />
      <span
        aria-hidden="true"
        className="text-hint h-[9px] leading-[8px] text-[var(--color-neutral-500)]"
      >
        {into ? '▲' : '▼'}
      </span>
    </div>
  )
}

/**
 * The right-hand rail column for one row: the loop's vertical line, the
 * horizontal stub into it, the `◀` at the node it points back to and the
 * `loop` label at the middle of its span.
 *
 * Absolutely positioned inside a 58 px column, exactly as the mock draws
 * it: the rail is a set of 1 px spans rather than a path, which is why
 * it needs no canvas.
 */
function LoopRail({ rail }: { rail: RailRow['rail'] }) {
  return (
    <div
      data-testid="graph-rail"
      data-down={rail.down}
      data-up={rail.up}
      data-arrow={rail.arrow}
      className="relative min-w-0"
    >
      {rail.down && (
        <span className="absolute top-1/2 right-[14px] bottom-0 block w-px bg-[var(--color-neutral-700)]" />
      )}
      {rail.up && (
        <span className="absolute top-0 right-[14px] block h-1/2 w-px bg-[var(--color-neutral-700)]" />
      )}
      {rail.stub && (
        <span className="absolute top-[14px] right-[14px] left-[2px] block h-px bg-[var(--color-neutral-700)]" />
      )}
      {rail.arrow && (
        <span
          aria-hidden="true"
          className="text-hint absolute top-[7px] -left-[4px] leading-none text-[var(--color-neutral-500)]"
        >
          ◀
        </span>
      )}
      {rail.label && (
        <span
          data-testid="graph-loop-label"
          className="absolute top-[18px] right-[20px] text-[9px] tracking-[0.06em] whitespace-nowrap text-[var(--color-neutral-500)]"
        >
          loop
        </span>
      )}
    </div>
  )
}

/** The kicker that opens a sub-list: which branch, and what opened it. */
function BranchLabel({ branch }: { branch: NonNullable<RailRow['branch']> }) {
  return (
    <p
      data-testid="graph-branch-label"
      data-branch={branchTag(branch)}
      className="text-hint mb-[4px] tracking-[0.1em] text-[var(--color-neutral-600)]"
    >
      {branchLabel(branch)}
    </p>
  )
}

/** One node's row: the glyph, the name and the detail column. */
function Row({
  row,
  onOpen,
  onMenu,
}: {
  row: RailRow
  onOpen: (node: string) => void
  onMenu: (node: GraphNode, x: number, y: number) => void
}) {
  const active = row.state === 'in_progress'

  return (
    <button
      type="button"
      data-testid="graph-row"
      data-node={row.node.name}
      data-state={row.state}
      data-depth={row.depth}
      {...(row.branch === null ? {} : { 'data-branch': branchTag(row.branch) })}
      onClick={() => {
        onOpen(row.node.name)
      }}
      onContextMenu={(event) => {
        event.preventDefault()
        onMenu(row.node, event.clientX, event.clientY)
      }}
      className={cn(
        'text-row flex w-full max-w-[420px] cursor-pointer items-center gap-[8px] rounded-lg border px-[10px] py-[6px] text-left text-[var(--color-neutral-300)]',
        active
          ? 'border-[var(--color-accent-600)] bg-[color-mix(in_srgb,var(--color-accent)_12%,var(--color-surface))] shadow-[0_0_0_1px_color-mix(in_srgb,var(--color-accent)_30%,transparent)]'
          : 'border-[var(--color-neutral-800)] bg-card',
        'hover:border-[var(--color-accent-500)]',
      )}
    >
      <span
        data-testid="graph-glyph"
        aria-hidden="true"
        className={cn(
          'w-[14px] flex-none',
          toneClass(row.tone),
          tonePulses(row.tone) && 'animate-ath-pulse',
        )}
      >
        {row.glyph}
      </span>
      <span className="min-w-0 flex-1 truncate">{row.node.name}</span>
      {row.detail !== '' && (
        <span
          data-testid="graph-detail"
          className="text-hint whitespace-nowrap text-[var(--color-neutral-500)]"
        >
          {row.detail}
        </span>
      )}
    </button>
  )
}

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

export function GraphRail({
  runId,
  taskId,
  onOpenNode,
  onOpenLibrary,
}: {
  /** The run in scope, from `?run=`. */
  runId: string | undefined
  /** The focused attempt, from `?task=`: what `move task here` moves. */
  taskId?: number | undefined
  /** Click a row: `?node=`, and the log pane (10 §Graph pane). */
  onOpenNode?: ((node: string) => void) | undefined
  /** `open definition`: the workflow library overlay (10 §Overlays). */
  onOpenLibrary?: (() => void) | undefined
}) {
  const detail = useRunDetail(runId)
  const workflow = detail?.workflow
  const { data: graph, isError, error } = useGraph(runId)
  const { data: source } = useSource(workflow)
  const queryClient = useQueryClient()

  // The elapsed half of `attempt n · elapsed` is `now − started`, and the
  // finest unit it prints is a second — the same reason the run list's
  // AGE column carries a clock, and the same clock.
  const now = useNow()
  const rows = railRows(graph, detail?.tasks, now)
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
        <div className="flex min-h-0 flex-1 flex-wrap items-start gap-x-[26px] gap-y-[22px] overflow-x-hidden overflow-y-auto px-[14px] pt-[18px] pb-[28px]">
          {/* 420 px of node card plus the mock's 58 px rail column: the
              rail is drawn beside the rows and not at the far edge of
              however wide the pane happens to be. */}
          <div className="flex min-w-0 max-w-[478px] flex-[1_1_280px] flex-col items-stretch">
            {rows.map((row) => (
              <div
                key={row.key}
                className="grid items-stretch"
                style={{ gridTemplateColumns: 'minmax(0, 1fr) 58px' }}
              >
                <div
                  className="flex min-w-0 flex-col items-stretch"
                  style={{ marginLeft: row.depth * INDENT_PX }}
                >
                  {row.first && row.branch !== null && <BranchLabel branch={row.branch} />}
                  <Row row={row} onOpen={onOpenNode ?? (() => undefined)} onMenu={openMenu} />
                  {(row.connector || row.intoJoin) && (
                    <Connector into={row.intoJoin} />
                  )}
                </div>
                <LoopRail rail={row.rail} />
              </div>
            ))}

            {notice !== null && (
              <p
                data-testid="graph-notice"
                role="status"
                className={cn(
                  'text-hint mt-[10px]',
                  notice.ok ? 'text-[var(--color-accent-300)]' : 'text-status-fail',
                )}
              >
                {notice.text}
              </p>
            )}
          </div>

          <Aside
            legend={legend}
            {...(source?.file === undefined ? {} : { file: source.file })}
            onOpenLibrary={onOpenLibrary}
          />
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

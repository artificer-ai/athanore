/**
 * The task drawer (`?overlay=task&task=`): "everything about one
 * attempt in one place" — payload, result, error, submissions, stats,
 * lineage and branch, with retry / move / set-status beside them
 * (`docs/v1/10-frontend.md` §Overlays, `docs/v1/04-engine.md` §Operator
 * operations, `docs/v1/08-api.md` §Tasks).
 *
 * It opens from the overview's NODES rows (T063a) and from the graph
 * pane's rows (T063e), and it is reached the way every overlay is: two
 * search parameters and nothing else. `?task=` outlives the overlay on
 * purpose — it is also the agent pane's focused attempt (T063c) — which
 * is what makes `focus stream` a navigation rather than a message: the
 * drawer closes, the pane cycle moves to the stream, and the attempt the
 * operator was reading is the one the transcript is of.
 *
 * **One read, `GET /api/tasks/{id}`.** It carries the row and its
 * submissions, so the drawer asks for nothing else until the move list
 * is opened, at which point the run's graph says which nodes are join
 * nodes. The task entry is the one `task.*` invalidates
 * (`realtime/invalidate.ts`), so a drawer left open over a running
 * attempt follows it.
 *
 * **The three actions are the three of 04 that take a task.**
 *
 * | action | call | precondition |
 * |---|---|---|
 * | `retry` | `POST /api/tasks/{id}/retry` | the attempt has stopped |
 * | `move` | `POST /api/tasks/{id}/move {node}` | the target is not a join |
 * | set status | `POST /api/tasks/{id}/status {status}` | none |
 *
 * A precondition the server enforces is enforced here too, by not
 * offering the row: `retry` is disabled while the attempt is still going
 * and says why, and the move list drops join nodes, which 04 §Fan-in
 * refuses with a `409`. Set-status offers all three targets bar the one
 * the attempt already has, because 04 gives the op no precondition and
 * this is the surface where an operator acts on this attempt
 * deliberately (`./taskDrawer.ts`, D175).
 *
 * **A refusal keeps the drawer up; a success closes it.** The pickers'
 * rule, for the pickers' reason (`./Pickers.tsx`): a `409` is corrected
 * by choosing differently, and a call that landed has changed the run
 * and reports on the toast surface.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, useState, type ReactNode } from 'react'
import { toast } from 'sonner'

import {
  getGraphApiRunsRunIdGraphGetOptions,
  getTaskApiTasksTaskIdGetOptions,
  moveTaskApiTasksTaskIdMovePostMutation,
  retryTaskApiTasksTaskIdRetryPostMutation,
  setStatusApiTasksTaskIdStatusPostMutation,
} from '../api/gen/@tanstack/react-query.gen'
import type { TaskDetail } from '../api/gen/types.gen'
import { taskTone, toneClass, tonePulses } from '../components/RunList'
import { actionError } from '../lib/errors'
import { cn } from '../lib/utils'
import { formatValue } from '../panes/kinds'
import { queryKeys } from '../realtime/invalidate'
import { OverlayDialog, OverlayHeader } from './OverlayPanel'
import {
  TASK_FALLBACKS,
  branchLines,
  canRetry,
  jsonBlock,
  lineageLine,
  priorityLine,
  stamp,
  statsRows,
  statusLabel,
  statusTargets,
} from './taskDrawer'

/** The dialog's accessible name, and the panel's header kicker. */
export const TASK_DRAWER_TITLE = 'task'

/** Why `retry` is not offered while an attempt is still going (04). */
export const RETRY_BLOCKED = 'this attempt has not stopped yet'

/** The outlined button of 10 §Components, at the drawer's size. */
const ACTION =
  'text-meta cursor-pointer rounded-lg border border-border px-[9px] py-[3px] ' +
  'text-[var(--color-neutral-300)] hover:border-[var(--color-accent-600)] ' +
  'hover:bg-[var(--color-accent-900)] disabled:cursor-default disabled:opacity-45 ' +
  'disabled:hover:border-border disabled:hover:bg-transparent'

export function TaskDrawer({
  open,
  taskId,
  onClose,
  onOpenTask,
  onFocusStream,
}: {
  open: boolean
  /** `?task=`: the attempt the drawer is about. */
  taskId: number | undefined
  onClose: () => void
  /** Open another attempt — the lineage's parent, a join's arrivals. */
  onOpenTask?: ((taskId: number) => void) | undefined
  /** Show this attempt's transcript in the agent pane (T063c). */
  onFocusStream?: ((taskId: number) => void) | undefined
}) {
  return (
    <OverlayDialog
      open={open}
      onClose={onClose}
      testId="task-drawer"
      width="w-[min(720px,94vw)]"
      placement="top"
    >
      {open && (
        // Remounted per attempt: the move list a drawer was halfway
        // through belongs to that attempt, and `?task=` swapped
        // underneath a live panel must not carry it into another one.
        <TaskDrawerBody
          key={taskId ?? 'none'}
          taskId={taskId}
          onClose={onClose}
          onOpenTask={onOpenTask}
          onFocusStream={onFocusStream}
        />
      )}
    </OverlayDialog>
  )
}

/** A line of prose where the attempt would be. */
function Notice({ children, alert }: { children: string; alert?: boolean }) {
  return (
    <p
      data-testid="task-drawer-notice"
      {...(alert === true ? { role: 'alert' } : { role: 'status' })}
      className="text-meta px-[14px] py-[14px] text-muted-foreground"
    >
      {children}
    </p>
  )
}

/** A titled block of the drawer; nothing is drawn for nothing to show. */
function Section({ label, children }: { label: string; children: ReactNode }) {
  return (
    <section data-testid="task-section" data-section={label}>
      <h3 className="text-kicker mb-[5px] text-[var(--color-neutral-500)]">{label}</h3>
      {children}
    </section>
  )
}

/** A value as the drawer shows it: indented JSON in a scrolling block. */
function Json({ value, testId }: { value: unknown; testId: string }) {
  return (
    <pre
      data-testid={testId}
      className="text-meta max-h-[220px] overflow-auto rounded-lg border border-[var(--color-neutral-900)] bg-[var(--color-neutral-900)] px-[9px] py-[7px] whitespace-pre-wrap text-[var(--color-neutral-300)]"
    >
      {jsonBlock(value)}
    </pre>
  )
}

/** The two-column meta grid the overview uses, at the drawer's size. */
function Kv({
  rows,
  testId,
}: {
  rows: ReadonlyArray<readonly [string, ReactNode]>
  testId: string
}) {
  return (
    <dl
      data-testid={testId}
      className="grid grid-cols-[minmax(0,120px)_minmax(0,1fr)] gap-x-[10px] gap-y-[3px]"
    >
      {rows.map(([label, value]) => (
        <div key={label} className="contents">
          <dt className="text-hint text-[var(--color-neutral-500)]">{label}</dt>
          <dd className="text-row [overflow-wrap:anywhere] text-[var(--color-neutral-300)]">
            {value}
          </dd>
        </div>
      ))}
    </dl>
  )
}

/** A task id drawn as the control that opens it. */
function TaskLink({
  taskId,
  onOpenTask,
}: {
  taskId: number
  onOpenTask?: ((taskId: number) => void) | undefined
}) {
  return (
    <button
      type="button"
      data-testid="task-link"
      data-task={taskId}
      disabled={onOpenTask === undefined}
      onClick={() => {
        onOpenTask?.(taskId)
      }}
      className="text-row cursor-pointer text-[var(--color-accent-200)] underline-offset-2 hover:underline disabled:cursor-default disabled:text-[var(--color-neutral-300)] disabled:no-underline"
    >
      #{taskId}
    </button>
  )
}

/** The attempt, and what the panel is until it has arrived. */
function TaskDrawerBody({
  taskId,
  onClose,
  onOpenTask,
  onFocusStream,
}: {
  taskId: number | undefined
  onClose: () => void
  onOpenTask?: ((taskId: number) => void) | undefined
  onFocusStream?: ((taskId: number) => void) | undefined
}) {
  // `queryFn` is put back explicitly for the reason `useRuns` does it
  // (`components/RunList/useRunList.ts`): the generator declares it
  // optional and `exactOptionalPropertyTypes` will not assign an
  // optional-and-absent property onto `useQuery`'s required one.
  const { queryFn, ...options } = getTaskApiTasksTaskIdGetOptions({
    path: { task_id: taskId ?? 0 },
  })
  const { data, isPending, isError, error } = useQuery({
    ...options,
    queryFn: queryFn!,
    enabled: taskId !== undefined,
  })

  if (taskId === undefined || isPending || isError) {
    return (
      <>
        <OverlayHeader title={TASK_DRAWER_TITLE} hint="esc close" />
        <Notice alert={isError}>
          {taskId === undefined
            ? 'no attempt is selected'
            : isError
              ? actionError(error, 'this attempt could not be read')
              : 'loading the attempt…'}
        </Notice>
      </>
    )
  }

  return (
    <TaskDrawerPanel
      task={data}
      onClose={onClose}
      onOpenTask={onOpenTask}
      onFocusStream={onFocusStream}
    />
  )
}

/** One attempt, drawn whole. */
function TaskDrawerPanel({
  task,
  onClose,
  onOpenTask,
  onFocusStream,
}: {
  task: TaskDetail
  onClose: () => void
  onOpenTask?: ((taskId: number) => void) | undefined
  onFocusStream?: ((taskId: number) => void) | undefined
}) {
  const queryClient = useQueryClient()
  const [moving, setMoving] = useState(false)
  const [refusal, setRefusal] = useState<string | null>(null)
  // Whether a call is out. A ref and not `isPending`, for the reason
  // D171 (1) gives: the pending state arrives a render later, and none
  // of these three can be un-done.
  const sending = useRef(false)

  const graphOptions = getGraphApiRunsRunIdGraphGetOptions({
    path: { run_id: task.run_id },
  })
  const { queryFn: graphFn, ...graphRest } = graphOptions
  const graph = useQuery({ ...graphRest, queryFn: graphFn!, enabled: moving })

  /**
   * The call landed: say so, refresh what it changed, and let the
   * overlay go.
   *
   * The four keys are the ones an enqueued, moved or re-statused attempt
   * makes stale — the run list's status and node columns, the run
   * detail's attempts, the graph's per-node state, and this attempt —
   * and they are refreshed rather than waited for, because `task.*` will
   * say the same thing a moment later and an operator's own action must
   * land whether or not this tab's stream is up (D171 (3)).
   */
  const settle = (text: string) => {
    toast(text)
    void queryClient.invalidateQueries({ queryKey: queryKeys.runs() })
    void queryClient.invalidateQueries({ queryKey: queryKeys.run(task.run_id) })
    void queryClient.invalidateQueries({ queryKey: queryKeys.graph(task.run_id) })
    void queryClient.invalidateQueries({ queryKey: queryKeys.task(task.id) })
    onClose()
  }

  const refuse = (error: unknown, fallback: string) => {
    sending.current = false
    setRefusal(actionError(error, fallback))
  }

  const retry = useMutation({
    ...retryTaskApiTasksTaskIdRetryPostMutation(),
    onSuccess: (result) => {
      settle(`retrying ${task.node} · task ${String(result.task_id)}`)
    },
    onError: (error) => {
      refuse(error, TASK_FALLBACKS.retry)
    },
  })

  const move = useMutation({
    ...moveTaskApiTasksTaskIdMovePostMutation(),
    onSuccess: (result, variables) => {
      settle(`moved to ${variables.body.node} · task ${String(result.task_id)}`)
    },
    onError: (error) => {
      refuse(error, TASK_FALLBACKS.move)
    },
  })

  const setStatus = useMutation({
    ...setStatusApiTasksTaskIdStatusPostMutation(),
    onSuccess: (_result, variables) => {
      settle(`#${String(task.id)} set to ${statusLabel(variables.body.status)}`)
    },
    onError: (error) => {
      refuse(error, TASK_FALLBACKS.status)
    },
  })

  /** Take the latch, or refuse to start a second call over the first. */
  const start = () => {
    if (sending.current) return false
    sending.current = true
    setRefusal(null)
    return true
  }

  const tone = taskTone(task.status)
  const lineage = lineageLine(task.lineage)
  const branch = branchLines(task.branch, formatValue)
  const stats = statsRows(task.stats, formatValue)
  const submissions = task.submissions ?? []
  const started = stamp(task.started)
  const finished = stamp(task.finished)
  const nodes = (graph.data?.nodes ?? []).filter((node) => !node.join)

  const meta: Array<readonly [string, ReactNode]> = [
    ['RUN', task.run_id],
    ['NODE', task.node],
    ['ATTEMPT', String(task.attempt)],
    ['PRIORITY', priorityLine(task.priority, task.explicit)],
    ['CREATED', stamp(task.created) ?? task.created],
    // Real data only: an attempt nobody has claimed has no start, and
    // one still running has no end. Neither is shown as a dash-shaped
    // hole in the grid.
    ...(started === undefined ? [] : [['STARTED', started] as const]),
    ...(finished === undefined ? [] : [['FINISHED', finished] as const]),
    ...(task.terminal ? [['TERMINAL', 'this attempt ended a branch'] as const] : []),
  ]

  return (
    <>
      <OverlayHeader
        title={`${TASK_DRAWER_TITLE} #${String(task.id)}`}
        gloss={`${task.node} · attempt ${String(task.attempt)}`}
        hint="esc close"
      >
        <span
          data-testid="task-status"
          className={cn(
            'text-hint tracking-[0.06em]',
            toneClass(tone),
            tonePulses(tone) && 'animate-ath-pulse',
          )}
        >
          {task.status}
        </span>
      </OverlayHeader>

      <div className="flex flex-none flex-wrap items-center gap-[6px] border-b border-[var(--color-neutral-900)] px-[14px] py-[9px]">
        <button
          type="button"
          data-testid="task-retry"
          disabled={!canRetry(task.status)}
          title={canRetry(task.status) ? undefined : RETRY_BLOCKED}
          onClick={() => {
            if (!canRetry(task.status) || !start()) return
            retry.mutate({ path: { task_id: task.id } })
          }}
          className={ACTION}
        >
          retry
        </button>

        <button
          type="button"
          data-testid="task-move"
          aria-expanded={moving}
          onClick={() => {
            setRefusal(null)
            setMoving((open) => !open)
          }}
          className={ACTION}
        >
          {moving ? 'cancel move' : 'move…'}
        </button>

        <span aria-hidden className="text-[var(--color-neutral-800)]">
          │
        </span>

        {statusTargets(task.status).map((target) => (
          <button
            key={target}
            type="button"
            data-testid="task-status-set"
            data-status={target}
            onClick={() => {
              if (!start()) return
              setStatus.mutate({
                path: { task_id: task.id },
                body: { status: target },
              })
            }}
            className={ACTION}
          >
            {statusLabel(target)}
          </button>
        ))}

        <div className="flex-1" />

        <button
          type="button"
          data-testid="task-focus-stream"
          disabled={onFocusStream === undefined}
          onClick={() => {
            onFocusStream?.(task.id)
          }}
          className={ACTION}
        >
          focus stream
        </button>
      </div>

      {moving && (
        <div
          data-testid="task-move-list"
          className="flex-none border-b border-[var(--color-neutral-900)] px-[14px] py-[9px]"
        >
          <h3 className="text-kicker mb-[5px] text-[var(--color-neutral-500)]">
            MOVE TO
          </h3>
          {graph.isError ? (
            // A run whose workflow this process does not have answers
            // the graph route with 404 `unknown_workflow` (08 §Graph
            // semantics), which is the one refusal a node list must not
            // draw as "no nodes".
            <p role="alert" className="text-meta text-status-fail">
              {actionError(graph.error, 'this run’s graph could not be read')}
            </p>
          ) : graph.isPending ? (
            <p role="status" className="text-meta text-muted-foreground">
              loading the nodes…
            </p>
          ) : nodes.length === 0 ? (
            <p role="status" className="text-meta text-muted-foreground">
              every node of this workflow is a join, and a task cannot be moved into one
            </p>
          ) : (
            <div className="flex flex-wrap gap-[6px]">
              {nodes.map((node) => (
                <button
                  key={node.name}
                  type="button"
                  data-testid="task-move-node"
                  data-node={node.name}
                  disabled={node.name === task.node}
                  onClick={() => {
                    if (!start()) return
                    move.mutate({
                      path: { task_id: task.id },
                      body: { node: node.name },
                    })
                  }}
                  className={ACTION}
                >
                  {node.name}
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="flex min-h-0 flex-1 flex-col gap-[14px] overflow-auto px-[14px] py-[12px]">
        <Kv rows={meta} testId="task-meta" />

        <Section label="LINEAGE">
          <p data-testid="task-lineage" className="text-row text-[var(--color-neutral-300)]">
            {lineage.text}
          </p>
          {lineage.parent !== undefined && (
            <p className="text-meta mt-[4px] text-muted-foreground">
              open the parent: <TaskLink taskId={lineage.parent} onOpenTask={onOpenTask} />
            </p>
          )}
          {lineage.arrivals.length > 0 && (
            <p className="text-meta mt-[4px] flex flex-wrap items-baseline gap-[6px] text-muted-foreground">
              arrivals:
              {lineage.arrivals.map((arrival) => (
                <TaskLink key={arrival} taskId={arrival} onOpenTask={onOpenTask} />
              ))}
            </p>
          )}
        </Section>

        {branch.length > 0 && (
          <Section label="BRANCH">
            <ul data-testid="task-branch" className="flex flex-col gap-[2px]">
              {branch.map((line) => (
                <li key={line} className="text-row text-[var(--color-neutral-300)]">
                  {line}
                </li>
              ))}
            </ul>
          </Section>
        )}

        {task.error != null && task.error !== '' && (
          <Section label="ERROR">
            <pre
              data-testid="task-error"
              className="text-meta max-h-[220px] overflow-auto rounded-lg border border-status-fail px-[9px] py-[7px] whitespace-pre-wrap text-status-fail"
            >
              {task.error}
            </pre>
          </Section>
        )}

        <Section label="PAYLOAD">
          <Json value={task.payload} testId="task-payload" />
        </Section>

        <Section label="RESULT">
          <Json value={task.result} testId="task-result" />
        </Section>

        {submissions.length > 0 && (
          <Section label="SUBMISSIONS">
            <ul data-testid="task-submissions" className="flex flex-col gap-[6px]">
              {submissions.map((submission) => (
                <li key={submission.id}>
                  <p className="text-hint text-muted-foreground">
                    #{submission.id} · {stamp(submission.created) ?? submission.created}
                  </p>
                  <Json
                    value={submission.payload}
                    testId={`task-submission-${String(submission.id)}`}
                  />
                </li>
              ))}
            </ul>
          </Section>
        )}

        {stats.length > 0 && (
          <Section label="STATS">
            <Kv rows={stats} testId="task-stats" />
          </Section>
        )}
      </div>

      {/* Under whichever of those the panel drew: a refusal arrives with
          the attempt still on screen, and choosing differently is how it
          is corrected. */}
      {refusal !== null && (
        <p
          role="alert"
          data-testid="task-drawer-error"
          className="text-meta flex-none border-t border-[var(--color-neutral-900)] px-[14px] py-[10px] text-status-fail"
        >
          {refusal}
        </p>
      )}
    </>
  )
}

/**
 * The four pickers (`t` retry, `m` move, `x` cancel task, `r` rerun
 * node, and the palette rows that open them): "a palette-style list of
 * the selected run's tasks (node, attempt, status) and, for move/rerun,
 * a second list of nodes" (`docs/v1/10-frontend.md` §Overlays).
 *
 * One component and not four, because they are one thing: a list, a
 * choice, and the `POST` that choice names (08 §Runs, §Tasks). What each
 * of them lists, what it refuses to list and what it says when it can
 * list nothing is `./pickers.ts`; this file is how it looks and what it
 * sends.
 *
 * **The four calls, one per picker** (04 §Operator operations):
 *
 * | picker | list | call |
 * |---|---|---|
 * | `t` | attempts that have stopped | `POST /api/tasks/{id}/retry` |
 * | `m` | every attempt, then the non-join nodes | `POST /api/tasks/{id}/move {node}` |
 * | `x` | attempts still going | `POST /api/tasks/{id}/status {status: "cancelled"}` |
 * | `r` | every node, joins included | `POST /api/runs/{id}/rerun {node}` |
 *
 * **`move` is two lists and one action.** The attempt is chosen first
 * and the panel becomes the node list; nothing has gone out until the
 * node is chosen too, so `esc` at either step leaves the run exactly as
 * it was. The list is remounted between the steps, which is what clears
 * the query the operator typed to find the attempt — a filter meant for
 * a task name would otherwise hide most of the nodes.
 *
 * **One action at a time**, for the New Run overlay's reason (D171 (1)):
 * every one of these four enqueues a task or stops one, and none of them
 * can be un-done. The latch is a ref and is taken synchronously, because
 * cmdk's `onSelect` fires on `⏎` as well as on a click and the pending
 * state arrives a render later.
 *
 * **A refusal keeps the panel up; a success closes it.** The two are not
 * the same to an operator: a `409` — the join `move` refuses, a rerun of
 * a join that never fired, a retry that raced the scheduler — is
 * corrected by picking another row, which is what the panel is for, so
 * the message is drawn on it. A call that landed has changed the run,
 * and the surface for something the operator is not being asked to
 * correct is the toast (10 §Components).
 *
 * **Two queries, both entries the app already holds.** The attempts are
 * `GET /api/runs/{id}`, the shared entry the overview and the graph pane
 * read; the nodes are `GET /api/runs/{id}/graph`, the entry that also
 * carries `join` — the one fact the picker needs and the workflow list
 * does not carry per run. Both are the generated queries, so they are
 * the keys `run.*` and `task.*` invalidate (10 §Realtime and caching)
 * and a picker opened over a run already on screen costs no request.
 *
 * The focus round trip is the palette's, for the palette's reason
 * (`./Palette.tsx`): this dialog opens from `?overlay=` and has no
 * `Dialog.Trigger`, so Radix would hand focus back to `<body>`.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Command } from 'cmdk'
import { Dialog } from 'radix-ui'
import { useRef, useState, type RefObject } from 'react'
import { toast } from 'sonner'

import {
  getGraphApiRunsRunIdGraphGetOptions,
  getRunApiRunsRunIdGetOptions,
  moveTaskApiTasksTaskIdMovePostMutation,
  rerunNodeApiRunsRunIdRerunPostMutation,
  retryTaskApiTasksTaskIdRetryPostMutation,
  setStatusApiTasksTaskIdStatusPostMutation,
} from '../api/gen/@tanstack/react-query.gen'
import type { GraphNode, TaskView } from '../api/gen/types.gen'
import { taskTone, toneClass } from '../components/RunList'
import { useKeyOwner } from '../keys'
import { actionError } from '../lib/errors'
import { cn } from '../lib/utils'
import { queryKeys } from '../realtime/invalidate'
import type { Overlay } from '../routes/search'
import { OverlayClose } from './OverlayPanel'
import {
  attemptDetail,
  eligibleNodes,
  eligibleTasks,
  isPicker,
  movingGloss,
  nodeDetail,
  PICKERS,
  type PickerKind,
} from './pickers'

/** The status an `x` writes (08 §Tasks, `POST /api/tasks/{id}/status`). */
const CANCELLED = 'cancelled' as const

/** What each call says when it was refused and the body said nothing. */
const FALLBACKS = {
  retry: 'the attempt was not retried',
  move: 'the task was not moved',
  cancel: 'the attempt was not cancelled',
  rerun: 'the node was not rerun',
} as const

/**
 * `GET /api/runs/{id}`: the attempts a task step lists.
 *
 * `queryFn` is put back explicitly for the reason `useRuns` does it
 * (`components/RunList/useRunList.ts`): the generator declares it
 * optional and `exactOptionalPropertyTypes` will not assign an
 * optional-and-absent property onto `useQuery`'s required one.
 */
function useRunTasks(runId: string | undefined, wanted: boolean) {
  const { queryFn, ...options } = getRunApiRunsRunIdGetOptions({
    path: { run_id: runId ?? '' },
  })
  return useQuery({
    ...options,
    queryFn: queryFn!,
    enabled: wanted && runId !== undefined,
  })
}

/**
 * `GET /api/runs/{id}/graph`: the nodes a node step lists, and the only
 * place the wire says which of them are joins (08 §Graph semantics).
 */
function useRunNodes(runId: string | undefined, wanted: boolean) {
  const { queryFn, ...options } = getGraphApiRunsRunIdGraphGetOptions({
    path: { run_id: runId ?? '' },
  })
  return useQuery({
    ...options,
    queryFn: queryFn!,
    enabled: wanted && runId !== undefined,
  })
}

export function Pickers({
  overlay,
  runId,
  onClose,
}: {
  /** `?overlay=`: one of the four opens this, anything else does not. */
  overlay: Overlay | undefined
  /** `?run=`: whose attempts and whose graph are being picked from. */
  runId: string | undefined
  onClose: () => void
}) {
  const kind = isPicker(overlay) ? overlay : undefined
  // An open overlay owns the keyboard: while it is up the app's global
  // map is off, so a `d` in here cannot reach the delete confirm
  // (`keys/scope.ts`, 10 §Keyboard).
  useKeyOwner(kind !== undefined)
  const restoreFocusTo = useRef<HTMLElement | null>(null)
  const input = useRef<HTMLInputElement | null>(null)

  return (
    <Dialog.Root
      open={kind !== undefined}
      onOpenChange={(next) => {
        // `esc`, the backdrop and a click outside all arrive here, so
        // there is one way out and the app writes `?overlay=` away once.
        if (!next) onClose()
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay
          data-testid="picker-backdrop"
          className="fixed inset-0 z-40 bg-[rgba(10,11,18,.72)]"
        />

        <Dialog.Content
          data-testid="picker"
          // The panel says what it is in two words and describes nothing
          // further; without this Radix warns about the description it
          // cannot find.
          aria-describedby={undefined}
          onOpenAutoFocus={(event) => {
            // The last moment at which the element the operator was on
            // is still the focused one.
            event.preventDefault()
            restoreFocusTo.current =
              document.activeElement instanceof HTMLElement
                ? document.activeElement
                : null
            input.current?.focus()
          }}
          onCloseAutoFocus={(event) => {
            // Radix's own restore goes to a trigger this dialog has not
            // got, which is `<body>` — the operator's place in the app,
            // lost. Ours goes back where focus came from.
            event.preventDefault()
            restoreFocusTo.current?.focus()
            restoreFocusTo.current = null
          }}
          className="text-body fixed top-[12vh] left-1/2 z-50 flex max-h-[76vh] w-[min(560px,92vw)] -translate-x-1/2 flex-col overflow-hidden rounded-lg border border-[var(--color-neutral-800)] bg-[var(--color-surface)] text-foreground shadow-[var(--shadow-lg)] max-md:top-[8px] max-md:max-h-[calc(100dvh-16px)] max-md:max-w-[calc(100vw-16px)]"
        >
          {kind !== undefined && (
            // Remounted per picker: the step a move is halfway through
            // belongs to that move, and `?overlay=` swapped underneath a
            // live panel must not carry it into another one.
            <PickerPanel
              key={kind}
              kind={kind}
              runId={runId}
              inputRef={input}
              onClose={onClose}
            />
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

/** A line of prose where the list would be. */
function Notice({ children, alert }: { children: string; alert?: boolean }) {
  return (
    <p
      data-testid="picker-notice"
      {...(alert === true ? { role: 'alert' } : { role: 'status' })}
      className="text-meta px-[14px] py-[14px] text-muted-foreground"
    >
      {children}
    </p>
  )
}

/** One picker, over the run it was opened on. */
function PickerPanel({
  kind,
  runId,
  inputRef,
  onClose,
}: {
  kind: PickerKind
  runId: string | undefined
  /** The dialog's open-focus lands here ({@link Pickers}). */
  inputRef: RefObject<HTMLInputElement | null>
  onClose: () => void
}) {
  const spec = PICKERS[kind]
  const queryClient = useQueryClient()

  // The attempt a move has already taken, and so which of its two lists
  // is on screen. A picker with one step never sets it.
  const [chosen, setChosen] = useState<TaskView | null>(null)
  const [refusal, setRefusal] = useState<string | null>(null)
  // Whether a call is out. A ref and not `isPending`, for the reason
  // D171 (1) gives: cmdk's `onSelect` fires on `⏎` as well as on a
  // click, and the pending state arrives a render later.
  const sending = useRef(false)

  const onTaskStep = spec.task !== null && chosen === null
  const step = onTaskStep ? spec.task : spec.node

  const detail = useRunTasks(runId, onTaskStep)
  const graph = useRunNodes(runId, !onTaskStep)

  /**
   * The call landed: say so, refresh what it changed, and let the
   * overlay go.
   *
   * The three keys are the ones an enqueued or cancelled attempt makes
   * stale — the run list's status and node columns, the run detail's
   * attempts, the graph's per-node state — and they are refreshed rather
   * than waited for, because `task.enqueued` will say the same thing a
   * moment later and an operator's own action must land whether or not
   * this tab's stream is up (the reason D171 (3) gives).
   */
  const settle = (text: string) => {
    toast(text)
    if (runId !== undefined) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.runs() })
      void queryClient.invalidateQueries({ queryKey: queryKeys.run(runId) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.graph(runId) })
    }
    onClose()
  }

  /** Refused: the panel stays up and the operator picks another row. */
  const refuse = (error: unknown, fallback: string) => {
    sending.current = false
    setRefusal(actionError(error, fallback))
  }

  const retry = useMutation({
    ...retryTaskApiTasksTaskIdRetryPostMutation(),
    onSuccess: (data, variables) => {
      settle(
        `retrying ${nodeOf(variables.path.task_id, detail.data?.tasks)} · task ${String(data.task_id)}`,
      )
    },
    onError: (error) => {
      refuse(error, FALLBACKS.retry)
    },
  })

  const move = useMutation({
    ...moveTaskApiTasksTaskIdMovePostMutation(),
    onSuccess: (data, variables) => {
      settle(`moved to ${variables.body.node} · task ${String(data.task_id)}`)
    },
    onError: (error) => {
      refuse(error, FALLBACKS.move)
    },
  })

  const cancel = useMutation({
    ...setStatusApiTasksTaskIdStatusPostMutation(),
    onSuccess: (_data, variables) => {
      settle(
        `cancelled ${nodeOf(variables.path.task_id, detail.data?.tasks)} · #${String(variables.path.task_id)}`,
      )
    },
    onError: (error) => {
      refuse(error, FALLBACKS.cancel)
    },
  })

  const rerun = useMutation({
    ...rerunNodeApiRunsRunIdRerunPostMutation(),
    onSuccess: (data, variables) => {
      settle(`rerunning ${variables.body.node} · task ${String(data.task_id)}`)
    },
    onError: (error) => {
      refuse(error, FALLBACKS.rerun)
    },
  })

  /** Take the latch, or refuse to start a second call over the first. */
  const start = () => {
    if (sending.current) return false
    sending.current = true
    setRefusal(null)
    return true
  }

  const pickTask = (task: TaskView) => {
    // A move names a node next; nothing has gone out yet, so this is a
    // step and not an action, and the latch stays where it is.
    if (spec.node !== null) {
      setChosen(task)
      setRefusal(null)
      return
    }
    if (!start()) return
    if (kind === 'pick-retry') {
      retry.mutate({ path: { task_id: task.id } })
    } else {
      cancel.mutate({ path: { task_id: task.id }, body: { status: CANCELLED } })
    }
  }

  const pickNode = (node: GraphNode) => {
    if (!start()) return
    if (kind === 'pick-rerun') {
      if (runId === undefined) return
      rerun.mutate({ path: { run_id: runId }, body: { node: node.name } })
    } else {
      if (chosen === null) return
      move.mutate({ path: { task_id: chosen.id }, body: { node: node.name } })
    }
  }

  const tasks = eligibleTasks(kind, detail.data?.tasks)
  const nodes = eligibleNodes(kind, graph.data?.nodes)
  const query = onTaskStep ? detail : graph
  const gloss = chosen === null ? (step?.gloss ?? '') : movingGloss(chosen)

  return (
    <>
      <div className="flex flex-none items-center gap-[10px] border-b border-[var(--color-neutral-900)] px-[14px] py-[10px]">
        <Dialog.Title className="text-kicker whitespace-nowrap text-[var(--color-accent-300)]">
          {spec.title}
        </Dialog.Title>
        <span
          data-testid="picker-gloss"
          className="text-hint truncate text-[var(--color-neutral-500)]"
        >
          {gloss}
        </span>
        <div className="flex-1" />
        <span className="text-hint whitespace-nowrap text-muted-foreground max-md:hidden">
          esc close
        </span>
        <OverlayClose />
      </div>

      {runId === undefined ? (
        <Notice>select a run to pick one of its attempts</Notice>
      ) : query.isError ? (
        // A run whose workflow this process does not have answers the
        // graph route with 404 `unknown_workflow` (08 §Graph semantics),
        // which is the one refusal a node list must not draw as "no
        // nodes".
        <Notice alert>
          {actionError(query.error, 'this run could not be read')}
        </Notice>
      ) : query.isPending ? (
        <Notice>{onTaskStep ? 'loading the attempts…' : 'loading the nodes…'}</Notice>
      ) : (onTaskStep ? tasks.length : nodes.length) === 0 ? (
        // Nothing this picker can act on. The panel says which of the
        // preconditions of 04 §Operator operations left it with nothing
        // to offer, rather than drawing an input over an empty box.
        <Notice>{step?.empty ?? ''}</Notice>
      ) : (
        <Command
          // Remounted between a move's two steps: the query that found
          // the attempt would otherwise stay in the box and hide most of
          // the nodes.
          key={onTaskStep ? 'tasks' : 'nodes'}
          label={spec.title}
          loop
          className="flex min-h-0 flex-1 flex-col"
        >
          <div className="flex flex-none items-center gap-[8px] border-b border-[var(--color-neutral-900)] px-[12px] py-[9px]">
            <span aria-hidden className="text-[var(--color-accent-400)]">
              ›
            </span>
            <Command.Input
              ref={inputRef}
              placeholder={step?.placeholder ?? ''}
              aria-label={spec.title}
              className="text-body flex-1 bg-transparent text-foreground outline-none placeholder:text-[var(--color-neutral-500)]"
            />
          </div>

          <Command.List className="min-h-0 flex-1 overflow-auto">
            <Command.Empty className="text-row px-[12px] py-[10px] text-muted-foreground">
              nothing matches
            </Command.Empty>

            {onTaskStep
              ? tasks.map((task) => (
                  <Row
                    key={task.id}
                    value={`#${String(task.id)} ${task.node}`}
                    name={task.node}
                    detail={attemptDetail(task)}
                    state={task.status}
                    testProps={{ 'data-task': String(task.id) }}
                    onSelect={() => {
                      pickTask(task)
                    }}
                  />
                ))
              : nodes.map((node) => (
                  <Row
                    key={node.name}
                    value={node.name}
                    name={node.name}
                    detail={nodeDetail(node)}
                    state={node.state}
                    testProps={{ 'data-node': node.name }}
                    onSelect={() => {
                      pickNode(node)
                    }}
                  />
                ))}
          </Command.List>
        </Command>
      )}

      {/* Under whichever of those the panel drew: a refusal arrives with
          the rows still on screen, and picking another one is how it is
          corrected. */}
      {refusal !== null && (
        <p
          role="alert"
          data-testid="picker-error"
          className="text-meta flex-none border-t border-[var(--color-neutral-900)] px-[14px] py-[10px] text-status-fail"
        >
          {refusal}
        </p>
      )}
    </>
  )
}

/** The node one of this run's attempts ran, for the toast that names it. */
function nodeOf(taskId: number, tasks: readonly TaskView[] | undefined): string {
  return (tasks ?? []).find((task) => task.id === taskId)?.node ?? `#${String(taskId)}`
}

/**
 * One row of either list: `name · detail · state`, the palette's three
 * columns, with the state coloured by the app's one status table (10
 * §Status colours).
 */
function Row({
  value,
  name,
  detail,
  state,
  testProps,
  onSelect,
}: {
  /** What cmdk keys and filters the row by; unique within the list. */
  value: string
  name: string
  detail: string
  /** A `TaskStatus` on an attempt, a `NodeState` on a node. */
  state: string
  /** `data-task` or `data-node`: which row this is, for a test. */
  testProps: Record<string, string>
  onSelect: () => void
}) {
  return (
    <Command.Item
      value={value}
      onSelect={onSelect}
      {...testProps}
      className="text-row grid cursor-pointer grid-cols-[minmax(0,160px)_minmax(0,1fr)_86px] items-center gap-[10px] border-t border-[var(--color-neutral-900)] px-[12px] py-[6px] data-[selected=true]:bg-[var(--color-neutral-900)]"
    >
      <span className="truncate text-[var(--color-neutral-300)]">{name}</span>
      <span className="text-hint truncate text-muted-foreground">{detail}</span>
      <span className={cn('text-hint truncate text-right', toneClass(taskTone(state)))}>
        {state}
      </span>
    </Command.Item>
  )
}

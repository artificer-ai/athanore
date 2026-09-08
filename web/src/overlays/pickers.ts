/**
 * What the four pickers are, minus the drawing of them: which of a run's
 * attempts each one may act on, which nodes it may send one to, and what
 * it says when there is nothing to pick (`docs/v1/10-frontend.md`
 * §Overlays, `docs/v1/04-engine.md` §Operator operations).
 *
 * A module of its own for the reason `./newRun.ts` and `./library.ts`
 * are: a file that exports a component and a function is one React Fast
 * Refresh cannot update in place (`.oxlintrc.json`,
 * `react/only-export-components`), and every rule below is worth testing
 * without a DOM.
 *
 * **A picker offers what the op would accept, and nothing else.** 04
 * §Operator operations gives each of the four a precondition, and the
 * server enforces it — but a list that offered a row the server is going
 * to refuse teaches the operator the rule by refusing them, which is the
 * worst way to learn it. So:
 *
 * - `retry` is refused while a task is still going (`ready`,
 *   `in_progress`, `waiting`): "a second attempt of a task that has one
 *   is two attempts of one task". The list is therefore the attempts
 *   that have *stopped*.
 * - `cancel task` is the mirror of it. `set_status` itself has no
 *   precondition, so this one is the palette's own words — "stop the
 *   running node" — read as the list: cancelling an attempt that already
 *   finished would overwrite the status it earned with `cancelled` and
 *   lose what actually happened, which is the thing 01 §Real data only
 *   forbids. The list is the attempts that are still going.
 * - `move` may take any attempt — one that has finished keeps the status
 *   it earned and the work is enqueued again elsewhere — but **never a
 *   join as the target**: 04 §Fan-in refuses it with a `409`, because a
 *   task moved into a join would be a join attempt holding one branch's
 *   payload with no arrival recorded, and the run would then wait for
 *   branches that had already arrived. Joins are dropped from the target
 *   list.
 * - `rerun` takes any node, joins included: a join replays the arrivals
 *   the store holds, which is the remedy for a branch that arrived late
 *   (04 §Failure and operator semantics). A join that never fired has no
 *   arrivals and is refused by the server, which is a fact about this
 *   run's history and not something a list of nodes can know.
 *
 * **Newest first.** `RunDetail.tasks` arrives oldest first, because it
 * is a timeline (07). A picker is not a timeline: the attempt an
 * operator reaches for is nearly always the one that just stopped, so
 * these lists are the reverse of it.
 */
import type { GraphNode, TaskStatus, TaskView } from '../api/gen/types.gen'
import type { Overlay } from '../routes/search'
import { plural } from './library'

/** The four overlays of 10 §Overlays' Pickers row, in its order. */
export const PICKER_OVERLAYS = [
  'pick-retry',
  'pick-move',
  'pick-cancel',
  'pick-rerun',
] as const

/** Which picker is up. A member of {@link PICKER_OVERLAYS}. */
export type PickerKind = (typeof PICKER_OVERLAYS)[number]

const PICKER_SET: ReadonlySet<string> = new Set(PICKER_OVERLAYS)

/** Whether `?overlay=` names a picker. */
export function isPicker(overlay: Overlay | undefined): overlay is PickerKind {
  return overlay !== undefined && PICKER_SET.has(overlay)
}

/**
 * The statuses an attempt is still going in.
 *
 * `Ops.retry` refuses these three and `move` cancels a task in one of
 * them before it enqueues the work elsewhere; they are the same three
 * `PENDING` in `athanore/engine/ops.py` names.
 */
export const PENDING: readonly TaskStatus[] = ['ready', 'in_progress', 'waiting']

/** One step of a picker: what it lists, and what it says when empty. */
export type PickerStep = {
  /** The header's second word: what picking a row here will do. */
  gloss: string
  /** The `›` input's placeholder. */
  placeholder: string
  /** The panel's answer when nothing is eligible — never an empty box. */
  empty: string
}

/** One picker: its name, and the one or two lists it walks. */
export type PickerSpec = {
  /** The palette's name for the command, and the panel's kicker. */
  title: string
  /** The attempt step, or `null` for a picker that only names a node. */
  task: PickerStep | null
  /** The node step, or `null` for a picker that only names an attempt. */
  node: PickerStep | null
}

/**
 * The four, with the palette's names for them (`./actions.ts`).
 *
 * `move` is the only one with both steps: an attempt, then where it
 * goes. `rerun node` names no attempt at all — 04's `rerun(run, node)`
 * takes the node's *last* payload, so the run and the node are the whole
 * operation.
 */
export const PICKERS: Record<PickerKind, PickerSpec> = {
  'pick-retry': {
    title: 'retry task',
    task: {
      gloss: 'an attempt that has stopped',
      placeholder: 'pick an attempt to retry',
      empty: 'no attempt of this run has stopped, so there is nothing to retry',
    },
    node: null,
  },
  'pick-move': {
    title: 'move task',
    task: {
      gloss: 'the attempt to move',
      placeholder: 'pick an attempt to move',
      empty: 'this run has no attempts to move',
    },
    node: {
      gloss: 'where to move it',
      placeholder: 'pick the node to move it to',
      empty: 'every node of this workflow is a join, and a task cannot be moved into one',
    },
  },
  'pick-cancel': {
    title: 'cancel task',
    task: {
      gloss: 'an attempt that is still going',
      placeholder: 'pick an attempt to cancel',
      empty: 'nothing in this run is still going, so there is nothing to cancel',
    },
    node: null,
  },
  'pick-rerun': {
    title: 'rerun node',
    task: null,
    node: {
      gloss: 'the node to replay',
      placeholder: 'pick a node to rerun',
      empty: 'this workflow has no nodes',
    },
  },
}

/** Whether `kind` may act on a task in `status`. */
function acts(kind: PickerKind, status: TaskStatus): boolean {
  const pending = PENDING.includes(status)
  if (kind === 'pick-retry') return !pending
  if (kind === 'pick-cancel') return pending
  return true
}

/**
 * The attempts `kind` may be run against, newest first.
 *
 * `undefined` — the run detail has not arrived — is an empty list, and
 * the panel draws its loading notice off the query rather than off this.
 */
export function eligibleTasks(
  kind: PickerKind,
  tasks: readonly TaskView[] | undefined,
): TaskView[] {
  if (tasks === undefined || PICKERS[kind].task === null) return []
  return tasks.filter((task) => acts(kind, task.status)).reverse()
}

/**
 * The nodes `kind` may target, in the order the graph route sent them —
 * generation order, then declaration order (08 §Graph semantics), which
 * is the order the graph pane draws.
 *
 * Joins are dropped for `move` and kept for `rerun`; see the note at the
 * top of this file for why the two differ.
 */
export function eligibleNodes(
  kind: PickerKind,
  nodes: readonly GraphNode[] | undefined,
): GraphNode[] {
  if (nodes === undefined || PICKERS[kind].node === null) return []
  return kind === 'pick-move' ? nodes.filter((node) => !node.join) : [...nodes]
}

/** An attempt's middle column: `attempt 2 · #41`. */
export function attemptDetail(task: TaskView): string {
  return `attempt ${String(task.attempt)} · #${String(task.id)}`
}

/**
 * A node's middle column: `join · 2 attempts`, with either half dropped
 * when it does not apply and nothing at all when neither does.
 *
 * A node this run has never reached says nothing rather than `0
 * attempts` (01 §Real data only), and `join` is written on the rows that
 * carry it because the rerun list is the one place an operator meets a
 * join in a flat list of names.
 */
export function nodeDetail(node: GraphNode): string {
  return [
    node.join ? 'join' : undefined,
    node.attempts === 0 ? undefined : plural(node.attempts, 'attempt'),
  ]
    .filter((part) => part !== undefined)
    .join(' · ')
}

/** What the header reads over the node list of a move already halfway. */
export function movingGloss(task: TaskView): string {
  return `moving ${task.node} · ${attemptDetail(task)}`
}

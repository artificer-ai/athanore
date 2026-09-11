/**
 * The shape the graph pane draws: the card one node puts on the canvas,
 * the branch chips a fan-out gives it, where every node and every edge
 * is placed, the detail line and the EDGES legend.
 *
 * Separate from `./GraphCanvas.tsx` for the reason `./requests.ts` is
 * separate from `./Requests.tsx`: a module that exports both a component
 * and a function is one React Fast Refresh cannot update in place
 * (`.oxlintrc.json`, `react/only-export-components`). It is also where
 * everything worth testing without a DOM lives — the ranks, the
 * grouping, the edges' geometry and the `k of n` text are all decided
 * here and merely painted there.
 *
 * **The layout is a pure function of the `generation` the route sent,
 * and there is no layout engine** (15, D206 (3)). `GET
 * /api/runs/{id}/graph` sends the nodes in generation order and, within
 * a generation, in declaration order (08 §Graph semantics, D131 (6)):
 * that is a rank and an order across it, which is the whole of what a
 * Dagre or an ELK pass would compute — except that such a pass would
 * also *reorder* the second half to reduce crossings, hiding an order
 * the workflow's author wrote deliberately. So {@link graphLayout} ranks
 * by generation, spreads a rank in the order it was given, centres it,
 * and does not minimise crossings.
 *
 * **Every node carries an explicit `width` and `height`.** React Flow
 * treats a node with both as measured, so the canvas needs no
 * measurement round trip: it draws the same picture on its first frame
 * as on its second, and it renders under jsdom, where nothing has a size
 * (D206 (4)).
 *
 * **A fan-out draws chips, never a second node** (D206 (2)). The wire's
 * `edges` name *nodes*, not attempts, so a canvas that drew `render`
 * once per branch would have to invent which copy each arrow into and
 * out of `render` connects — the invention 01 §Real data only forbids.
 * The rail this replaced could use sub-lists because a list has no
 * arrows. What the sub-lists carried moves inside the one node: a
 * {@link BranchChip} per branch, keyed and labelled by its attempts'
 * frame stack and coloured by that branch's own state.
 *
 * **A branch is its attempts' frame stack.** The wire gives a branch
 * entry its innermost fan-out (`from_task`) and the attempts in it, and
 * two branches of one fan-out are two entries carrying the same
 * `from_task` (08 §Graph semantics, D131) — so the entry alone cannot
 * say *which* branch it is, and pairing one node's entries with the next
 * node's by position is wrong the moment a branch finishes out of order,
 * which a fan-out on one pool slot does routinely. What can say it is on
 * the attempts: `TaskView.branch` is the whole `{fanout, index, count,
 * key}` stack, which is the grouping key 08 names. So a chip is keyed by
 * the frames of the attempts its entry lists, and a run whose attempts
 * have not arrived falls back to the entry's position — the most the
 * graph response alone can say (15, D167 (1)).
 *
 * **A node with no attempt has no chip.** `branches` is empty for a node
 * this run has not reached, and a node reached by a single path carries
 * one entry whose `from_task` is `null` — the canvas is this run's
 * history projected onto the workflow's shape, not a prediction of the
 * branches it is going to open.
 */
import { MarkerType, type Edge, type Node } from '@xyflow/react'

import type {
  AthanoreApiSchemasTasksBranchFrame,
  GraphBranch,
  GraphNode,
  GraphOut,
  NodeState,
  TaskView,
} from '../../api/gen/types.gen'
import { taskTone, type StatusTone } from '../../components/RunList'
import { formatCount, formatSeconds, preview } from './overview'

/** How much of a branch's key the chip's title prints. */
export const BRANCH_KEY_CHARS = 24

/* -------------------------------------------------------------------- */
/* Glyphs                                                                */
/* -------------------------------------------------------------------- */

/**
 * The card's marks (10 §Graph pane): `✓` done, `●` active, `✗` failed,
 * `·` everything else, and `⋈` on a join whatever it is doing.
 *
 * A join keeps its own glyph in every state because the glyph is what
 * says the node is a fan-in — it is the node the branches arrive at, and
 * a `✓` there would be indistinguishable from any other completed node.
 * Its *colour* is still its state's, so a failed join is a red `⋈`.
 */
export const GLYPHS = {
  done: '✓',
  active: '●',
  failed: '✗',
  idle: '·',
  join: '⋈',
} as const

/**
 * The mark for `node` in `state`: the state's, or `⋈` when it is a
 * fan-in.
 *
 * `state` is passed rather than read off the node because a branch of a
 * fan-out has a state of its own ({@link branchState}) and the chip that
 * draws it may want the same table; on the card it is `node.state`.
 */
export function nodeGlyph(node: GraphNode, state: NodeState): string {
  if (node.join) return GLYPHS.join
  switch (state) {
    case 'done':
      return GLYPHS.done
    case 'in_progress':
      return GLYPHS.active
    case 'failed':
    case 'dead_letter':
      return GLYPHS.failed
    default:
      return GLYPHS.idle
  }
}

/*
 * The colour a card carries is `taskTone(state)` (10 §Status colours).
 * `NodeState` is the seven task statuses plus `idle`, so the app's one
 * status table answers for all of it: `taskTone` maps the seven and
 * returns `muted` for anything it has no row for, which is exactly what
 * a node no attempt has ever existed for should be. There is no second
 * table here.
 */

/* -------------------------------------------------------------------- */
/* The detail line                                                       */
/* -------------------------------------------------------------------- */

/** Every attempt of one node, in the order the run detail sent them. */
function attemptsOf(tasks: readonly TaskView[] | undefined, node: string): TaskView[] {
  return (tasks ?? []).filter((task) => task.node === node)
}

/** How long one attempt took, in seconds, or `undefined` if unknown. */
function attemptSeconds(task: TaskView): number | undefined {
  if (task.started == null || task.finished == null) return undefined
  const started = Date.parse(task.started)
  const finished = Date.parse(task.finished)
  if (Number.isNaN(started) || Number.isNaN(finished)) return undefined
  return (finished - started) / 1000
}

/** The tokens an attempt reported, or `undefined` when none did. */
function attemptTokens(task: TaskView): number | undefined {
  const total = (task.stats ?? {})['total_tokens']
  return typeof total === 'number' && Number.isFinite(total) ? total : undefined
}

/**
 * `18,204 · 9s` — what these attempts spent and how long they took.
 *
 * Summed exactly as `athanore/plugins/builtin/overview.py` sums the
 * NODES row, so the graph's detail and the overview's row are one
 * number: tokens from the stats entries that carry one, duration as
 * wall-clock `finished − started`. **Neither half is zero-filled** — a
 * node no agent measured shows the duration alone, and a node nothing is
 * known about shows `''` rather than `0 · 0s` (01 §Real data only).
 */
function spentText(attempts: readonly TaskView[]): string {
  let tokens: number | undefined
  let seconds: number | undefined

  for (const task of attempts) {
    const spent = attemptTokens(task)
    if (spent !== undefined) tokens = (tokens ?? 0) + spent
    const took = attemptSeconds(task)
    if (took !== undefined) seconds = (seconds ?? 0) + took
  }

  return [
    tokens === undefined ? undefined : formatCount(tokens),
    seconds === undefined ? undefined : formatSeconds(seconds),
  ]
    .filter((part) => part !== undefined)
    .join(' · ')
}

/** `attempt 2 · 105s` — the attempt in flight, and how long it has run. */
function runningText(attempts: readonly TaskView[], now: number): string | undefined {
  const running = attempts.filter((task) => task.status === 'in_progress').at(-1)
  if (running === undefined) return undefined

  const label = `attempt ${String(running.attempt)}`
  if (running.started == null) return label
  const started = Date.parse(running.started)
  if (Number.isNaN(started)) return label
  return `${label} · ${formatSeconds(Math.max(0, now - started) / 1000)}`
}

/**
 * The card's second line (10 §Graph pane), in this order:
 *
 * 1. `2 of 3 arrived` — a join with a fan-out still open. It is the one
 *    thing an operator watching a fan-in is waiting for, so it outranks
 *    everything the join's own attempts could say.
 * 2. `attempt 2 · 105s` — a node in progress, from the attempt that is
 *    running and the clock. `now` is passed in rather than read here so
 *    that the caller owns the tick (`useNow`) and a test owns the time.
 * 3. `waiting` — parked on a request (08 §Graph semantics' `waiting`),
 *    ahead of what earlier attempts of the same node spent, because the
 *    node is at a gate and that is the fact.
 * 4. `18,204 · 9s` — what its attempts spent, when anything measured it.
 * 5. `''` for `idle`: no attempt has ever existed, so there is nothing
 *    to say and the column stays empty.
 * 6. the state word otherwise — `ready`, `failed`, `cancelled`,
 *    `dead_letter`, `done` — which is the server's own word for what the
 *    node is doing, not a phrase invented here.
 */
export function nodeDetail(
  node: GraphNode,
  state: NodeState,
  attempts: readonly TaskView[],
  now: number,
): string {
  const arrivals = node.arrivals
  if (arrivals != null) {
    return `${String(arrivals.arrived)} of ${String(arrivals.count)} arrived`
  }

  if (state === 'in_progress') {
    const running = runningText(attempts, now)
    if (running !== undefined) return running
  }
  if (state === 'waiting') return 'waiting'

  const spent = spentText(attempts)
  if (spent !== '') return spent
  return state === 'idle' ? '' : state
}
/* -------------------------------------------------------------------- */
/* The branches of one node                                              */
/* -------------------------------------------------------------------- */

/** Which branch a chip is, and what to call it. */
export type BranchKey = {
  /** The fan-out task the branch came out of (`branches[].from_task`). */
  fromTask: number
  /** This branch's index in that fan-out, when the attempts say. */
  index?: number
  /** How many branches the fan-out opened, when the attempts say. */
  count?: number
  /** The payload this branch was given, printed, when it carried one. */
  key?: string
  /** Its position among this fan-out's branches on this node, from `0`. */
  ordinal: number
}

/**
 * `branch 2 of 3 · beta · from task 26` — what a chip is called.
 *
 * Everything in it came off the wire: the index and the count are the
 * branch frame the attempts carry, the key is the payload that branch
 * was given, and the fan-out is the task whose return value opened it.
 * A run whose attempts this build has not read falls back to the
 * position — `branch 2 · from task 26` — because the ordinal is what the
 * graph response alone can say, and a number invented for the label
 * would be a claim about which branch this is (01 §Real data only).
 */
export function branchLabel(branch: BranchKey): string {
  const which =
    branch.index === undefined
      ? `branch ${String(branch.ordinal + 1)}`
      : branch.count === undefined
        ? `branch ${String(branch.index + 1)}`
        : `branch ${String(branch.index + 1)} of ${String(branch.count)}`
  return [which, branch.key, `from task ${String(branch.fromTask)}`]
    .filter((part) => part !== undefined)
    .join(' · ')
}

/** The branch a chip is about, as a `data-` attribute and a React key. */
export function branchTag(branch: BranchKey): string {
  return `${String(branch.fromTask)}:${String(branch.index ?? branch.ordinal)}`
}

/**
 * `2/3` — the chip's own face, which is as much of the label as fits.
 *
 * The full sentence is the chip's `title`; this is the part that can be
 * read at a glance, and it says only what the wire said: `#2` where the
 * attempts have not arrived and only the position is known, because
 * `2/3` there would be a claim about how many branches the fan-out
 * opened.
 */
function branchShort(branch: BranchKey): string {
  if (branch.index === undefined) return `#${String(branch.ordinal + 1)}`
  if (branch.count === undefined) return `#${String(branch.index + 1)}`
  return `${String(branch.index + 1)}/${String(branch.count)}`
}

/**
 * The branch-frame stack of the attempts in `entry`, from the run's own
 * task rows — the grouping key 08 §Graph semantics names.
 *
 * `GraphBranch` carries the *innermost* fan-out and the attempts, and
 * two branches of one fan-out are two entries with the same `from_task`
 * (D131). The stack that actually tells them apart is on the attempts:
 * `TaskView.branch` is `[{fanout, index, count, key}]`, outermost first
 * (08 §Tasks). So the chips are keyed by the attempts' own frames, which
 * means one branch's chip on `render` and that same branch's chip on
 * `report` carry the same tag however differently the two nodes' entries
 * happen to be ordered.
 *
 * `undefined` when the run detail has not arrived, or when it carries
 * none of the entry's attempts — a graph read before the run, or a
 * transcript trimmed by retention. The caller falls back to the entry's
 * position, which is what the wire alone can say.
 */
function framesOf(
  entry: GraphBranch,
  byId: Map<number, TaskView>,
): AthanoreApiSchemasTasksBranchFrame[] | undefined {
  for (const id of entry.tasks ?? []) {
    const task = byId.get(id)
    if (task !== undefined && (task.branch ?? []).length > 0) return task.branch
  }
  return undefined
}

/**
 * 08 §Graph semantics' precedence, as a rank per state: **lower wins**,
 * and the order is the member order of `NodeState` in the OpenAPI
 * document, which is where D131 puts the rule.
 *
 * A `Record<NodeState, number>` rather than a list, because the record
 * is what makes the copy safe: a member a later Athanore adds to the
 * contract fails to compile here rather than silently ranking below
 * everything. Every member but `idle` is the name of a task status,
 * which is what lets the same table rank a set of attempts.
 */
const STATE_RANK: Record<NodeState, number> = {
  in_progress: 0,
  waiting: 1,
  ready: 2,
  dead_letter: 3,
  failed: 4,
  done: 5,
  cancelled: 6,
  idle: 7,
}

/**
 * The state of one branch's attempts, by that precedence.
 *
 * A fan-out whose branches are in different states is the case this
 * exists for: `render` is `in_progress` as a *node* while one branch of
 * it is running, one is queued and one is done, and three chips drawn in
 * the node's own colour would each claim to be the running one (15, D167
 * (2)). `idle` is what no attempt at all means, here as there — and it
 * is also what a status this build has no rank for leaves behind, rather
 * than a rank invented for it.
 */
export function branchState(attempts: readonly TaskView[]): NodeState {
  let best: NodeState = 'idle'
  const ranks = STATE_RANK as Record<string, number | undefined>
  for (const task of attempts) {
    const rank = ranks[task.status]
    if (rank !== undefined && rank < STATE_RANK[best]) best = task.status as NodeState
  }
  return best
}
/* -------------------------------------------------------------------- */
/* The cards and the layout                                              */
/* -------------------------------------------------------------------- */

/** One branch of one fan-out, as a chip inside the node it fanned. */
export type BranchChip = {
  /** {@link branchTag}: the `data-branch` attribute and the React key. */
  tag: string
  /** {@link branchLabel}: the whole sentence, as the chip's `title`. */
  label: string
  /** {@link branchShort}: what the chip actually draws. */
  short: string
  /** This branch's own state, by 08's precedence ({@link branchState}). */
  state: NodeState
  /** Its colour: `taskTone(state)` (10 §Status colours). */
  tone: StatusTone
}

/** The card one node draws, and everything the canvas paints on it. */
export type NodeCard = {
  /** The node itself, as the graph route sent it. */
  node: GraphNode
  /** What the node is doing: `node.state`, the wire's own word. */
  state: NodeState
  /** The mark: {@link nodeGlyph}. */
  glyph: string
  /** The colour: `taskTone(state)` (10 §Status colours). */
  tone: StatusTone
  /** The second line: {@link nodeDetail}. */
  detail: string
  /** The fan-outs this node ran in, or `[]` when it ran in none. */
  branches: BranchChip[]
}

/** A node of the canvas: one workflow node, placed and sized. */
export type GraphFlowNode = Node<NodeCard, 'athanore'>

/** What an edge of the canvas carries beyond its geometry. */
export type EdgeMeta = {
  /** `forward`, `back` or `join`, as the wire named it. */
  kind: string
  /** How often this run took the arrow (08 §Graph semantics). */
  traversed: number
}

/** An edge of the canvas. Every one of them is a `smoothstep`. */
export type GraphFlowEdge = Edge<EdgeMeta, 'smoothstep'> & {
  pathOptions?: { borderRadius?: number; offset?: number }
}

/**
 * The card's fixed size, in absolute pixels, and the gaps between cards.
 *
 * Pixels and not `rem`, because D195 is that **what scales is type, not
 * density**: the type ramp grows the glyph, the name and the detail line
 * inside a card whose geometry — and therefore the picture the canvas
 * draws — stays where the operator left it. `fitView` is what makes a
 * larger drawing fit the pane, not a larger drawing.
 */
export const NODE_WIDTH = 208
/** The glyph and the name, then the detail line. */
export const NODE_HEIGHT = 56
/** What a node that draws branch chips adds to {@link NODE_HEIGHT}. */
export const BRANCH_ROW = 18
/** Between two cards of one rank. */
export const COLUMN_GAP = 32
/** Between one rank and the next. */
export const RANK_GAP = 56

/** What `styles/reactflow.css` dashes: an arrow this run never took. */
export const UNTAKEN_CLASS = 'graph-edge-untaken'

/** The handles the layout names, which `GraphCanvas` draws (D206 (5)). */
export const HANDLES = {
  top: 'top',
  bottom: 'bottom',
  loopOut: 'right-source',
  loopIn: 'right-target',
} as const

/**
 * The chips one node draws: its attempts' branches, in branch order.
 *
 * A join takes none — a join is where the branches stop being separate,
 * and 10 §Graph pane draws it once with the `⋈` glyph — and so does a
 * node reached by a single path, whose one entry carries `from_task:
 * null`.
 *
 * The ordinal counts within one fan-out, so a node under two fan-outs
 * (one nested in the other) numbers each from zero. It is only the
 * fallback key: {@link framesOf} is what normally identifies the branch,
 * and it is exact.
 */
function chipsOf(node: GraphNode, byId: Map<number, TaskView>): BranchChip[] {
  if (node.join) return []
  const chips: { branch: BranchKey; chip: BranchChip }[] = []
  const seen = new Map<number, number>()

  for (const entry of node.branches ?? []) {
    const fromTask = entry.from_task
    if (fromTask == null) continue
    const ordinal = seen.get(fromTask) ?? 0
    seen.set(fromTask, ordinal + 1)

    const inner = framesOf(entry, byId)?.at(-1)
    const branch: BranchKey = {
      fromTask,
      ordinal,
      ...(inner === undefined ? {} : { index: inner.index, count: inner.count }),
      ...(inner?.key === undefined ? {} : { key: preview(inner.key, BRANCH_KEY_CHARS) }),
    }
    const attempts = (entry.tasks ?? [])
      .map((id) => byId.get(id))
      .filter((task): task is TaskView => task !== undefined)
    // A branch whose attempts the run detail does not carry is drawn in
    // the node's state: the chip is still that node in that branch, and
    // inventing `idle` for it would be worse than saying less.
    const state = attempts.length === 0 ? node.state : branchState(attempts)
    chips.push({
      branch,
      chip: {
        tag: branchTag(branch),
        label: branchLabel(branch),
        short: branchShort(branch),
        state,
        tone: taskTone(state),
      },
    })
  }

  // A fan-out enqueues its branches in index order, so this is usually
  // already true; it makes it true rather than incidental, and it is a
  // no-op for a run whose branch indices are not known.
  chips.sort(
    (a, b) =>
      a.branch.fromTask - b.branch.fromTask ||
      (a.branch.index ?? a.branch.ordinal) - (b.branch.index ?? b.branch.ordinal),
  )
  return chips.map((entry) => entry.chip)
}

/** How tall the card for `card` is: the chips are a row of their own. */
function cardHeight(card: NodeCard): number {
  return NODE_HEIGHT + (card.branches.length > 0 ? BRANCH_ROW : 0)
}

/**
 * What one edge of the response draws (D206 (5)).
 *
 * A back edge leaves and arrives on the node's **right-hand side**, as a
 * `smoothstep` that bows out, and it is the only kind that carries a
 * `loop` label — the mock's right-hand rail idiom, kept, without asking
 * the operator to read a colour. Forward and `join` edges run down the
 * ranks, bottom to top, and a `join` edge is drawn exactly as a forward
 * one: the `⋈` glyph on the target says the node is a fan-in (D167 (4))
 * and the EDGES aside lists the arrow by its kind, so a third geometry
 * would be a third notation for a fact already stated twice.
 *
 * The weight says whether *this run* took it: an edge with `traversed
 * === 0` is dashed and drawn a step back, and one taken more than once
 * is labelled `×n`.
 */
function flowEdge(
  from: string,
  to: string,
  kind: string,
  traversed: number,
): GraphFlowEdge {
  const back = kind === 'back'
  const taken = traversed > 0
  const times = traversed > 1 ? `×${String(traversed)}` : undefined
  const label = back
    ? ['loop', times].filter((part) => part !== undefined).join(' ')
    : times
  const stroke = taken ? 'var(--color-neutral-700)' : 'var(--color-neutral-800)'

  return {
    id: `${kind}:${from}→${to}`,
    source: from,
    target: to,
    sourceHandle: back ? HANDLES.loopOut : HANDLES.bottom,
    targetHandle: back ? HANDLES.loopIn : HANDLES.top,
    type: 'smoothstep',
    ...(back ? { pathOptions: { borderRadius: 12, offset: 24 } } : {}),
    ...(label === undefined ? {} : { label }),
    ...(taken ? {} : { className: UNTAKEN_CLASS }),
    markerEnd: { type: MarkerType.ArrowClosed, color: stroke, width: 14, height: 14 },
    data: { kind, traversed },
    zIndex: 0,
  }
}

/**
 * The canvas: one node per workflow node, placed in ranks, and one edge
 * per arrow the response carries.
 *
 * `tasks` is `RunDetail.tasks` — the attempts the detail line is
 * computed from and the branch frames the chips are keyed by, which the
 * pane has already read for the run — and `now` is the clock the running
 * attempt's elapsed time is measured against.
 *
 * The placement, and it is the whole algorithm:
 *
 * - the nodes are bucketed by `generation`, keeping the route's order
 *   within a bucket, and a node's **rank** is its generation's index
 *   among the distinct generations present — so a workflow whose
 *   generations are not contiguous leaves no empty band;
 * - a rank's height is the tallest card in it, and its `y` is the
 *   running sum of the ranks above it plus one {@link RANK_GAP} each;
 * - the `i`th of `n` cards in a rank sits at `(i − (n − 1) / 2) ×
 *   (NODE_WIDTH + COLUMN_GAP)`, so a linear workflow is a straight
 *   column and a fan-out spreads symmetrically about it.
 *
 * An edge naming a node the response does not carry is dropped rather
 * than drawn to nowhere: `edges` are the finalized graph's and the nodes
 * are this run's, so the two need not name the same things.
 */
export function graphLayout(
  graph: GraphOut | undefined,
  tasks: readonly TaskView[] | undefined,
  now: number,
): { nodes: GraphFlowNode[]; edges: GraphFlowEdge[] } {
  const byId = new Map((tasks ?? []).map((task) => [task.id, task]))
  const source = graph?.nodes ?? []

  const cards = source.map((node): NodeCard => {
    const branches = chipsOf(node, byId)
    return {
      node,
      state: node.state,
      glyph: nodeGlyph(node, node.state),
      tone: taskTone(node.state),
      detail: nodeDetail(node, node.state, attemptsOf(tasks, node.name), now),
      branches,
    }
  })

  const ranks = new Map<number, NodeCard[]>()
  for (const card of cards) {
    const rank = ranks.get(card.node.generation)
    if (rank === undefined) ranks.set(card.node.generation, [card])
    else rank.push(card)
  }

  const nodes: GraphFlowNode[] = []
  let y = 0
  for (const generation of [...ranks.keys()].sort((a, b) => a - b)) {
    const rank = ranks.get(generation) ?? []
    let tallest = 0
    rank.forEach((card, index) => {
      const height = cardHeight(card)
      tallest = Math.max(tallest, height)
      nodes.push({
        id: card.node.name,
        type: 'athanore',
        position: {
          x: (index - (rank.length - 1) / 2) * (NODE_WIDTH + COLUMN_GAP),
          y,
        },
        width: NODE_WIDTH,
        height,
        data: card,
      })
    })
    y += tallest + RANK_GAP
  }

  const drawn = new Set(nodes.map((node) => node.id))
  const edges = (graph?.edges ?? [])
    .filter((edge) => drawn.has(edge.from) && drawn.has(edge.to))
    .map((edge) => flowEdge(edge.from, edge.to, edge.kind, edge.traversed))

  return { nodes, edges }
}

/* -------------------------------------------------------------------- */
/* The EDGES legend                                                      */
/* -------------------------------------------------------------------- */

/** The four kinds the legend lists (10 §Graph pane). */
export type LegendKind = 'edge' | 'loop' | 'join' | 'gate'

/** One line of the legend: the kind, and what it is about. */
export type LegendRow = { kind: LegendKind; text: string }

/** `EdgeKind` on the wire against the word the legend prints. */
const EDGE_KINDS: Record<string, LegendKind> = {
  forward: 'edge',
  back: 'loop',
  join: 'join',
}

/**
 * The plain-language description of each kind (10 §Graph pane).
 *
 * Carried as the row's `title`, so the legend reads as the mock's does —
 * a kind and the arrow it is about — while the sentence that explains
 * the kind is one hover away rather than repeated on every line.
 */
export const LEGEND_GLOSS: Record<LegendKind, string> = {
  edge: 'a step from one node to the next',
  loop: 'a node routing back to an earlier one, drawn bowing out to the right',
  join: 'a branch arriving at a fan-in, which runs once every branch has',
  gate: 'a node parked on a question, waiting on an answer from you',
}

/**
 * The EDGES block: the graph's own arrows, grouped by kind in the order
 * 10 lists them, and then the nodes that are at a gate right now.
 *
 * The arrows are the ones `GET /api/runs/{id}/graph` sent, in the order
 * it sent them, and nothing is collapsed into a chain: the mock wrote
 * `prompt → product → architecture → engineering` because its data was a
 * hand-written string, and folding real edges into chains would be this
 * pane inventing a path through the graph.
 *
 * `gate` is not an edge kind — it is the `waiting` state of 08 §Graph
 * semantics — and it is in the legend because the mock's is, as the one
 * thing in the block that is about the run rather than the workflow. A
 * run with nothing at a gate has no gate line, which is the same rule
 * every other line follows: a kind with no arrows is not listed.
 */
export function legendRows(graph: GraphOut | undefined): LegendRow[] {
  const edges = graph?.edges ?? []
  const arrow = (kind: LegendKind) =>
    edges
      .filter((edge) => EDGE_KINDS[edge.kind] === kind)
      .map((edge) => ({ kind, text: `${edge.from} → ${edge.to}` }))

  const gates = (graph?.nodes ?? [])
    .filter((node) => node.state === 'waiting')
    .map((node) => ({ kind: 'gate' as const, text: `${node.name} · waiting` }))

  return [...arrow('edge'), ...arrow('loop'), ...arrow('join'), ...gates]
}

/* -------------------------------------------------------------------- */
/* The right-click menu                                                  */
/* -------------------------------------------------------------------- */

/**
 * Why `move task here` is refused, or `undefined` when it is offered.
 *
 * The join case is the one 10 §Graph pane names and the one the API
 * refuses with `409 conflict` (08 §Tasks, 04 §Fan-in): a task cannot be
 * moved into a fan-in, because a join is dispatched by the branches
 * arriving at it and not by a task being put there. The menu says so
 * rather than posting a request it knows will be refused.
 */
export function moveRefusal(
  node: GraphNode,
  taskId: number | undefined,
): string | undefined {
  if (node.join) return 'a task cannot be moved into a join'
  if (taskId === undefined) return 'this run has no attempt to move'
  return undefined
}

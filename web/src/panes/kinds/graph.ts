/**
 * The shape the graph pane draws: the rail's rows, the sub-lists a
 * fan-out opens, the loop rails, the detail column and the EDGES legend
 * (`docs/v1/10-frontend.md` §Graph pane, `docs/v1/08-api.md` §Graph
 * semantics).
 *
 * Separate from `./GraphRail.tsx` for the reason `./requests.ts` is
 * separate from `./Requests.tsx`: a module that exports both a component
 * and a function is one React Fast Refresh cannot update in place
 * (`.oxlintrc.json`, `react/only-export-components`). It is also where
 * everything worth testing without a DOM lives — the row order, the
 * nesting, the rails and the `k of n` text are all decided here and
 * merely painted there.
 *
 * **No layout is computed that the API already did.** `GET
 * /api/runs/{id}/graph` sends the nodes in generation order and, within
 * a generation, in declaration order — "the order 10 §Graph pane draws,
 * so the SPA renders the list it is given" (08). Nothing here sorts
 * them. What it does is *group*: a node's `branches` say which fan-out
 * each of its attempts belongs to, and 10 draws one indented sub-list
 * per branch.
 *
 * **A branch is its attempts' frame stack.** The wire gives a branch
 * entry its innermost fan-out (`from_task`) and the attempts in it, and
 * two branches of one fan-out are two entries carrying the same
 * `from_task` (08 §Graph semantics, D131) — so the entry alone cannot
 * say *which* branch it is, and pairing one node's entries with the next
 * node's by position is wrong the moment a branch finishes out of order,
 * which a fan-out on one pool slot does routinely. What can say it is on
 * the attempts: `TaskView.branch` is the whole `{fanout, index, count,
 * key}` stack, which is the grouping key 08 names. So a sub-list is
 * keyed by the frames of the attempts its entry lists, and a run whose
 * attempts have not arrived falls back to the entry's position — the
 * most the graph response alone can say (15, D167).
 *
 * **Depth is one.** A branch nested inside another opens its own
 * sub-list beside the outer one rather than inside it: the rail is a
 * list of rows, and one indent is what tells a branch from the trunk.
 * Its label still names the fan-out it came out of, which is the
 * innermost frame, so the nesting is legible without being drawn.
 *
 * **A node with no attempt has no branch.** `branches` is empty for a
 * node this run has not reached, so an idle node is drawn at the parent
 * indent — the rail is this run's history projected onto the workflow's
 * shape, not a prediction of the branches it is going to open.
 */
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

/** How much of a branch's key the sub-list's label prints. */
export const BRANCH_KEY_CHARS = 24

/* -------------------------------------------------------------------- */
/* Glyphs                                                                */
/* -------------------------------------------------------------------- */

/**
 * The rail's marks (10 §Graph pane): `✓` done, `●` active, `✗` failed,
 * `·` everything else, and `⋈` on a join whatever it is doing.
 *
 * A join keeps its own glyph in every state because the glyph is what
 * says the row is a fan-in — it is drawn back at the parent indent with
 * the sub-lists arriving into it, and a `✓` there would be
 * indistinguishable from any other completed node. Its *colour* is
 * still its state's, so a failed join is a red `⋈`.
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
 * `state` is passed rather than read off the node because a row inside a
 * sub-list is one *branch* of that node and has a state of its own
 * ({@link branchState}); at the parent indent it is `node.state`.
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
 * The colour a row carries is `taskTone(state)` (10 §Status colours).
 * `NodeState` is the seven task statuses plus `idle`, so the app's one
 * status table answers for all of it: `taskTone` maps the seven and
 * returns `muted` for anything it has no row for, which is exactly what
 * a node no attempt has ever existed for should be. There is no second
 * table here.
 */

/* -------------------------------------------------------------------- */
/* The detail column                                                     */
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
 * The row's right-hand column (10 §Graph pane), in this order:
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
/* The rows                                                              */
/* -------------------------------------------------------------------- */

/** Which sub-list a row belongs to, and what to call it. */
export type BranchKey = {
  /** The fan-out task the branch came out of (`branches[].from_task`). */
  fromTask: number
  /** This branch's index in that fan-out, when the attempts say. */
  index?: number
  /** How many branches the fan-out opened, when the attempts say. */
  count?: number
  /** The payload this branch was given, printed, when it carried one. */
  key?: string
  /** Its position among this fan-out's sub-lists, from `0`. */
  ordinal: number
}

/**
 * `branch 2 of 3 · beta · from task 26` — what a sub-list is called.
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

/** The sub-list a row is in, as a `data-` attribute and a React key. */
export function branchTag(branch: BranchKey): string {
  return `${String(branch.fromTask)}:${String(branch.index ?? branch.ordinal)}`
}

/** The loop rail's four parts on one row, as the mock draws them. */
export type Rail = {
  /** A line from the middle of the row down to the next. */
  down: boolean
  /** A line from the previous row down to the middle of this one. */
  up: boolean
  /** The horizontal stub joining the row to the rail. */
  stub: boolean
  /** `◀`: the row a back edge points at. */
  arrow: boolean
  /** The `loop` label, once per back edge, at the middle of its span. */
  label: boolean
}

/** One drawn row of the rail. */
export type RailRow = {
  /** Unique and stable: a node appears once per branch it ran in. */
  key: string
  /** The node itself, as the graph route sent it. */
  node: GraphNode
  /**
   * What *this row* is doing: the node's state at the parent indent, and
   * the branch's own state inside a sub-list ({@link branchState}).
   */
  state: NodeState
  /** `0` at the parent indent, `1` inside a sub-list. */
  depth: 0 | 1
  /** The sub-list this row is in, or `null` at the parent indent. */
  branch: BranchKey | null
  /** Whether this row opens its sub-list (where the label is drawn). */
  first: boolean
  /** Whether it closes it (where `▲` into the join is drawn). */
  last: boolean
  /** The mark: {@link nodeGlyph}. */
  glyph: string
  /** The colour: `taskTone(state)` (10 §Status colours). */
  tone: StatusTone
  /** The right-hand column: {@link nodeDetail}. */
  detail: string
  /** `▼`: another row follows in this row's own list. */
  connector: boolean
  /** `▲`: this closes a sub-list and a join node follows it. */
  intoJoin: boolean
  /** The loop rail on this row. */
  rail: Rail
}

/** A sub-list being built: one branch of one fan-out. */
type Block = {
  key: string
  branch: BranchKey
  /** The node, and the attempts of it that ran in this branch. */
  rows: { node: GraphNode; tasks: number[] }[]
}

/** The top-level sequence: rows at the parent indent, and sub-lists. */
type Group = { kind: 'row'; node: GraphNode } | { kind: 'block'; block: Block }

/** No rail at all, which is what most rows carry. */
function noRail(): Rail {
  return { down: false, up: false, stub: false, arrow: false, label: false }
}

/**
 * The branch-frame stack of the attempts in `entry`, from the run's own
 * task rows — the grouping key 08 §Graph semantics names.
 *
 * `GraphBranch` carries the *innermost* fan-out and the attempts, and
 * two branches of one fan-out are two entries with the same `from_task`
 * (D131). The stack that actually tells them apart is on the attempts:
 * `TaskView.branch` is `[{fanout, index, count, key}]`, outermost first
 * (08 §Tasks). So the sub-lists are keyed by the attempts' own frames,
 * which means one branch's `render` and that same branch's `report` land
 * in the same sub-list however differently the two nodes' entries happen
 * to be ordered.
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
 * it is running, one is queued and one is done, and three rows drawn
 * with the node's own glyph would each claim to be the running one (15,
 * D167). `idle` is what no attempt at all means, here as there — and it
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

/**
 * The top-level sequence: the nodes at the parent indent, and the
 * sub-lists their fan-outs opened, in the order each is first seen.
 *
 * A sub-list is appended where its **first** node lands, so a fan-out's
 * branches sit immediately under the node that opened them and the join
 * that closes them comes after both — which is the picture 10 §Graph
 * pane describes, out of nothing but the generation order the route
 * already sent.
 *
 * A join is always a parent-indent row (10: "drawn back at the parent
 * indent"), whatever branch its own attempt ran in: the join is where
 * the branches stop being separate.
 */
function group(nodes: readonly GraphNode[], byId: Map<number, TaskView>): Group[] {
  const groups: Group[] = []
  const blocks = new Map<string, Block>()

  for (const node of nodes) {
    const branches = node.branches ?? []
    const fanned = node.join ? [] : branches.filter((entry) => entry.from_task != null)

    // A parent-indent row for a node that ran outside any fan-out, for
    // an idle node, and for every join. A node with both kinds of entry
    // — an attempt inside a branch and one outside it — draws both, so
    // neither history is hidden.
    if (fanned.length === 0 || branches.some((entry) => entry.from_task == null)) {
      groups.push({ kind: 'row', node })
    }

    // The ordinal counts within one fan-out, so a node under two
    // fan-outs (one nested in the other) numbers each from zero. It is
    // only the fallback key: `framesOf` is what normally identifies the
    // branch, and it is exact.
    const seen = new Map<number, number>()
    for (const entry of fanned) {
      const fromTask = entry.from_task
      if (fromTask == null) continue
      const ordinal = seen.get(fromTask) ?? 0
      seen.set(fromTask, ordinal + 1)

      const frames = framesOf(entry, byId)
      const inner = frames?.at(-1)
      const key =
        frames === undefined
          ? `${String(fromTask)}#${String(ordinal)}`
          : frames.map((frame) => `${String(frame.fanout)}:${String(frame.index)}`).join('/')

      let block = blocks.get(key)
      if (block === undefined) {
        block = {
          key,
          branch: {
            fromTask,
            ordinal,
            ...(inner === undefined ? {} : { index: inner.index, count: inner.count }),
            ...(inner?.key === undefined ? {} : { key: preview(inner.key, BRANCH_KEY_CHARS) }),
          },
          rows: [],
        }
        blocks.set(key, block)
        groups.push({ kind: 'block', block })
      }
      block.rows.push({ node, tasks: [...(entry.tasks ?? [])] })
    }
  }

  return ordered(groups)
}

/**
 * The same groups, with each run of consecutive sub-lists in branch
 * order.
 *
 * A fan-out enqueues its branches in index order, so the sub-lists are
 * already in that order the moment the node under the fan-out is drawn;
 * this only makes it true rather than incidental, and it is a no-op for
 * a run whose branch indices are not known. Sorting a *run* of blocks
 * rather than the whole list is what keeps the parent-indent rows where
 * the generation order put them.
 */
function ordered(groups: Group[]): Group[] {
  const out = [...groups]
  let start = 0
  while (start < out.length) {
    if (out[start]?.kind !== 'block') {
      start += 1
      continue
    }
    let end = start
    while (out[end + 1]?.kind === 'block') end += 1
    const run = out.slice(start, end + 1) as { kind: 'block'; block: Block }[]
    run.sort(
      (a, b) =>
        a.block.branch.fromTask - b.block.branch.fromTask ||
        (a.block.branch.index ?? a.block.branch.ordinal) -
          (b.block.branch.index ?? b.block.branch.ordinal),
    )
    out.splice(start, run.length, ...run)
    start = end + 1
  }
  return out
}

/**
 * Whether the group after `index` — skipping the sibling sub-lists of
 * the same fan-out region — is a join node.
 *
 * That is what "a join node closes the sub-lists" is: the sub-lists'
 * last rows connect into it with `▲` (10 §Graph pane), and a fan-out
 * whose branches simply end draws no arrow into anything.
 */
function closedByJoin(groups: readonly Group[], index: number): boolean {
  for (let next = index + 1; next < groups.length; next += 1) {
    const group_ = groups[next]
    if (group_ === undefined) return false
    if (group_.kind === 'block') continue
    return group_.node.join
  }
  return false
}

/**
 * The rail's rows, in draw order, with their connectors and their loops.
 *
 * `tasks` is `RunDetail.tasks` — the attempts the detail column is
 * computed from and the branch frames the sub-lists are keyed by, which
 * the pane has already read for the run — and `now` is the clock the
 * running attempt's elapsed time is measured against.
 */
export function railRows(
  graph: GraphOut | undefined,
  tasks: readonly TaskView[] | undefined,
  now: number,
): RailRow[] {
  const byId = new Map((tasks ?? []).map((task) => [task.id, task]))
  const groups = group(graph?.nodes ?? [], byId)
  const rows: RailRow[] = []

  groups.forEach((group_, index) => {
    if (group_.kind === 'row') {
      const node = group_.node
      rows.push({
        key: node.name,
        node,
        state: node.state,
        depth: 0,
        branch: null,
        first: false,
        last: false,
        glyph: nodeGlyph(node, node.state),
        tone: taskTone(node.state),
        detail: nodeDetail(node, node.state, attemptsOf(tasks, node.name), now),
        connector: index < groups.length - 1,
        intoJoin: false,
        rail: noRail(),
      })
      return
    }

    const { block } = group_
    const joined = closedByJoin(groups, index)
    block.rows.forEach((entry, position) => {
      const last = position === block.rows.length - 1
      const attempts = entry.tasks
        .map((id) => byId.get(id))
        .filter((task): task is TaskView => task !== undefined)
      // A branch whose attempts the run detail does not carry is drawn
      // in the node's state: the row is still that node in that branch,
      // and inventing `idle` for it would be worse than saying less.
      const state = attempts.length === 0 ? entry.node.state : branchState(attempts)
      rows.push({
        key: `${block.key}/${entry.node.name}`,
        node: entry.node,
        state,
        depth: 1,
        branch: block.branch,
        first: position === 0,
        last,
        glyph: nodeGlyph(entry.node, state),
        tone: taskTone(state),
        detail: nodeDetail(entry.node, state, attempts, now),
        connector: !last,
        intoJoin: last && joined,
        rail: noRail(),
      })
    })
  })

  return withLoops(rows, graph)
}

/**
 * The right-hand rail: one vertical line per back edge, from the row it
 * points at down to the row it leaves, with `◀` on the target and one
 * `loop` label at the middle of its span (10 §Graph pane, and the mock's
 * `railDown` / `railUp` / `railJoin` / `railArrow` / `railLabel`).
 *
 * A node drawn several times — once per branch it ran in — is anchored
 * at its **first** row, because a rail is drawn once and the node it
 * loops to is one node however many branches entered it.
 *
 * A back edge whose ends this run has not drawn is skipped rather than
 * drawn to nowhere: `edges` are the finalized graph's and the rows are
 * this run's history, so the two need not name the same nodes.
 */
function withLoops(rows: RailRow[], graph: GraphOut | undefined): RailRow[] {
  const anchor = new Map<string, number>()
  rows.forEach((row, index) => {
    if (!anchor.has(row.node.name)) anchor.set(row.node.name, index)
  })

  for (const edge of graph?.edges ?? []) {
    if (edge.kind !== 'back') continue
    const target = anchor.get(edge.to)
    const source = anchor.get(edge.from)
    if (target === undefined || source === undefined) continue

    const top = Math.min(target, source)
    const bottom = Math.max(target, source)
    for (let index = top; index < bottom; index += 1) {
      const row = rows[index]
      if (row !== undefined) row.rail.down = true
    }
    for (let index = top + 1; index <= bottom; index += 1) {
      const row = rows[index]
      if (row !== undefined) row.rail.up = true
    }
    for (const index of [top, bottom]) {
      const row = rows[index]
      if (row !== undefined) row.rail.stub = true
    }
    const arrow = rows[target]
    if (arrow !== undefined) arrow.rail.arrow = true
    const label = rows[Math.round((top + bottom) / 2)]
    if (label !== undefined) label.rail.label = true
  }

  return rows
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
  loop: 'a node routing back to an earlier one, drawn on the right-hand rail',
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

/**
 * What a refused action said, as the menu prints it.
 *
 * The generated client throws the parsed error body — `{error, code}`,
 * the API's one error shape (08 §Conventions) — rather than an `Error`,
 * so both are read and neither is assumed, exactly as `./log.ts` reads
 * the composer's.
 */
export function actionError(error: unknown, fallback: string): string {
  if (typeof error === 'object' && error !== null) {
    const message = (error as { error?: unknown }).error
    if (typeof message === 'string' && message !== '') return message
    if (error instanceof Error && error.message !== '') return error.message
  }
  if (typeof error === 'string' && error.trim() !== '') return error
  return fallback
}

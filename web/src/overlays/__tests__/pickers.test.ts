/**
 * `overlays/pickers.ts`: which attempts and which nodes each of the four
 * pickers may offer.
 *
 * These are the rules the server enforces, asserted on the client that
 * has to agree with it: a row the picker offers and the op refuses is a
 * `409` the operator only finds by trying.
 */
import { describe, expect, it } from 'vitest'

import type { GraphNode, TaskStatus, TaskView } from '../../api/gen/types.gen'
import { PALETTE_COMMANDS } from '../actions'
import {
  attemptDetail,
  eligibleNodes,
  eligibleTasks,
  isPicker,
  movingGloss,
  nodeDetail,
  PENDING,
  PICKER_OVERLAYS,
  PICKERS,
} from '../pickers'

/** One attempt of `node`, as `GET /api/runs/{id}` sends it. */
function task(id: number, node: string, status: TaskStatus, attempt = 1): TaskView {
  return {
    id,
    run_id: 'aaaa1111',
    node,
    attempt,
    status,
    priority: 0,
    explicit: false,
    terminal: false,
    created: '2026-09-08T08:00:00Z',
  }
}

/** One node of the run's graph, as `GET /api/runs/{id}/graph` sends it. */
function graphNode(name: string, over: Partial<GraphNode> = {}): GraphNode {
  return {
    name,
    generation: 0,
    join: false,
    live: false,
    attempts: 0,
    state: 'idle',
    ...over,
  }
}

/** One attempt in every status, oldest first, as the wire orders them. */
const EVERY_STATUS: TaskView[] = [
  task(1, 'prepare', 'done'),
  task(2, 'implement', 'ready'),
  task(3, 'gate', 'in_progress'),
  task(4, 'review', 'waiting'),
  task(5, 'qa', 'failed'),
  task(6, 'approve', 'dead_letter'),
  task(7, 'merge', 'cancelled'),
]

/** The nodes of a workflow with a fan-in in the middle of it. */
const NODES: GraphNode[] = [
  graphNode('prepare', { state: 'done', attempts: 1 }),
  graphNode('implement', { state: 'in_progress', attempts: 2 }),
  graphNode('gather', { join: true }),
  graphNode('merge'),
]

function names(nodes: readonly GraphNode[]): string[] {
  return nodes.map((node) => node.name)
}

function ids(tasks: readonly TaskView[]): number[] {
  return tasks.map((one) => one.id)
}

describe('isPicker', () => {
  it('is the four overlays 10 §Overlays lists under Pickers', () => {
    expect([...PICKER_OVERLAYS]).toEqual([
      'pick-retry',
      'pick-move',
      'pick-cancel',
      'pick-rerun',
    ])
    for (const overlay of PICKER_OVERLAYS) expect(isPicker(overlay)).toBe(true)
  })

  it('is not any other overlay, nor none at all', () => {
    expect(isPicker('palette')).toBe(false)
    expect(isPicker('edit')).toBe(false)
    expect(isPicker(undefined)).toBe(false)
  })
})

describe('eligibleTasks', () => {
  it('offers retry only the attempts that have stopped', () => {
    // `Ops.retry` refuses `ready`, `in_progress` and `waiting`: a second
    // attempt of a task that has one is two attempts of one task.
    expect(ids(eligibleTasks('pick-retry', EVERY_STATUS))).toEqual([7, 6, 5, 1])
  })

  it('offers cancel only the attempts that are still going', () => {
    expect(ids(eligibleTasks('pick-cancel', EVERY_STATUS))).toEqual([4, 3, 2])
    expect(PENDING).toEqual(['ready', 'in_progress', 'waiting'])
  })

  it('offers move every attempt, whatever it did', () => {
    expect(ids(eligibleTasks('pick-move', EVERY_STATUS))).toEqual([
      7, 6, 5, 4, 3, 2, 1,
    ])
  })

  it('lists them newest first, against the wire’s timeline order', () => {
    const rows = eligibleTasks('pick-move', EVERY_STATUS)
    expect(rows[0]?.id).toBe(7)
    // ...and leaves the caller's list alone: `reverse` is in place, and
    // the run detail is a shared cache entry.
    expect(EVERY_STATUS[0]?.id).toBe(1)
  })

  it('offers rerun no attempts at all: it names a node', () => {
    expect(eligibleTasks('pick-rerun', EVERY_STATUS)).toEqual([])
    expect(PICKERS['pick-rerun'].task).toBeNull()
  })

  it('is empty while the run detail is still in flight', () => {
    expect(eligibleTasks('pick-retry', undefined)).toEqual([])
  })
})

describe('eligibleNodes', () => {
  it('hides join nodes from move: 04 §Fan-in refuses one with a 409', () => {
    expect(names(eligibleNodes('pick-move', NODES))).toEqual([
      'prepare',
      'implement',
      'merge',
    ])
  })

  it('keeps join nodes for rerun, which replays their arrivals', () => {
    expect(names(eligibleNodes('pick-rerun', NODES))).toEqual([
      'prepare',
      'implement',
      'gather',
      'merge',
    ])
  })

  it('keeps the order the graph route sent, which is what 08 fixes', () => {
    expect(names(eligibleNodes('pick-rerun', NODES))).toEqual(names(NODES))
  })

  it('offers no nodes to the pickers that name an attempt', () => {
    expect(eligibleNodes('pick-retry', NODES)).toEqual([])
    expect(eligibleNodes('pick-cancel', NODES)).toEqual([])
  })

  it('is empty while the graph is still in flight', () => {
    expect(eligibleNodes('pick-move', undefined)).toEqual([])
  })
})

describe('row text', () => {
  it('writes an attempt as `attempt n · #id`', () => {
    expect(attemptDetail(task(41, 'gate', 'failed', 2))).toBe('attempt 2 · #41')
  })

  it('says nothing about a node this run has never reached', () => {
    expect(nodeDetail(graphNode('merge'))).toBe('')
  })

  it('counts a node’s attempts, with the `s` earned', () => {
    expect(nodeDetail(graphNode('prepare', { attempts: 1 }))).toBe('1 attempt')
    expect(nodeDetail(graphNode('implement', { attempts: 2 }))).toBe('2 attempts')
  })

  it('marks a join, which is the one row a flat list cannot tell', () => {
    expect(nodeDetail(graphNode('gather', { join: true }))).toBe('join')
    expect(nodeDetail(graphNode('gather', { join: true, attempts: 1 }))).toBe(
      'join · 1 attempt',
    )
  })

  it('names the attempt a move is halfway through', () => {
    expect(movingGloss(task(41, 'gate', 'failed', 2))).toBe(
      'moving gate · attempt 2 · #41',
    )
  })
})

describe('PICKERS', () => {
  it('gives every picker at least one step, and move both', () => {
    for (const kind of PICKER_OVERLAYS) {
      const spec = PICKERS[kind]
      expect(spec.task !== null || spec.node !== null).toBe(true)
    }
    expect(PICKERS['pick-move'].task).not.toBeNull()
    expect(PICKERS['pick-move'].node).not.toBeNull()
  })

  it('carries the palette’s own names for the four commands', () => {
    expect(PICKERS['pick-retry'].title).toBe('retry task')
    expect(PICKERS['pick-move'].title).toBe('move task')
    expect(PICKERS['pick-cancel'].title).toBe('cancel task')
    expect(PICKERS['pick-rerun'].title).toBe('rerun node')

    // ...which are the catalogue's, so the row an operator pressed and
    // the panel it opened are called the same thing.
    const catalogue = new Set(PALETTE_COMMANDS.map((command) => command.name))
    for (const kind of PICKER_OVERLAYS) {
      expect(catalogue).toContain(PICKERS[kind].title)
    }
  })
})

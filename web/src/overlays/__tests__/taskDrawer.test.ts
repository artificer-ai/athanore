/**
 * `overlays/taskDrawer.ts`: what the drawer says about one attempt,
 * without a DOM.
 */
import { describe, expect, it } from 'vitest'

import { formatValue } from '../../panes/kinds'
import {
  STATUS_TARGETS,
  branchLines,
  canRetry,
  jsonBlock,
  lineageLine,
  priorityLine,
  stamp,
  statsRows,
  statusLabel,
  statusTargets,
} from '../taskDrawer'

describe('lineageLine', () => {
  it('names the parent for every reason the engine writes', () => {
    // `start`, `transition` and `retry` come from the runner and the
    // join repo; `manual_retry`, `move` and `rerun` from `Ops`.
    for (const reason of [
      'transition',
      'retry',
      'join',
      'manual_retry',
      'move',
      'rerun',
    ]) {
      const line = lineageLine({ reason, from: 12 })
      expect(line.parent).toBe(12)
      expect(line.text).toContain('task #12')
      // A sentence, not the stored enum member: no row reads
      // `manual_retry` or `{"reason": …}` at the operator.
      expect(line.text).not.toContain('_')
    }
  })

  it('reads a failed attempt’s retry as what it is', () => {
    expect(lineageLine({ reason: 'manual_retry', from: 40 }).text).toBe(
      'an operator’s retry of task #40',
    )
  })

  it('stops rather than trailing off when no parent was recorded', () => {
    expect(lineageLine({ reason: 'start' })).toEqual({
      text: 'the run’s first attempt',
      parent: undefined,
      arrivals: [],
    })
    expect(lineageLine({ reason: 'move' }).text).toBe('moved here by an operator')
  })

  it('carries a join’s arrivals, and only the ids among them', () => {
    const line = lineageLine({
      reason: 'join',
      from: 26,
      arrivals: [31, 'nonsense', 32, -1],
    })

    expect(line.arrivals).toEqual([31, 32])
    expect(line.text).toContain('the join closing the fan-out at task #26')
  })

  it('names a reason this build has never heard of', () => {
    // 01 §Real data only: a lineage written by a later Athanore is
    // printed under its own name rather than dropped.
    expect(lineageLine({ reason: 'teleport', from: 3 }).text).toBe(
      'enqueued for “teleport”, from task #3',
    )
  })

  it('says so when there is no lineage at all', () => {
    for (const lineage of [null, undefined]) {
      expect(lineageLine(lineage).text).toBe('this attempt records no lineage')
    }
    expect(lineageLine({}).text).toBe('enqueued for “unknown”')
  })
})

describe('branchLines', () => {
  it('numbers a branch from one and names its fan-out and its key', () => {
    expect(
      branchLines([{ fanout: 26, index: 1, count: 3, key: 'beta' }], formatValue),
    ).toEqual(['branch 2 of 3 · beta · from task #26'])
  })

  it('drops the key a branch was not given, outermost frame first', () => {
    expect(
      branchLines(
        [
          { fanout: 4, index: 0, count: 2 },
          { fanout: 9, index: 1, count: 2, key: 7 },
        ],
        formatValue,
      ),
    ).toEqual(['branch 1 of 2 · from task #4', 'branch 2 of 2 · 7 · from task #9'])
  })

  it('has no lines for an attempt outside any fan-out', () => {
    expect(branchLines([], formatValue)).toEqual([])
    expect(branchLines(undefined, formatValue)).toEqual([])
  })
})

describe('the actions’ preconditions', () => {
  it('refuses retry while the attempt is still going (04)', () => {
    for (const status of ['ready', 'in_progress', 'waiting'] as const) {
      expect(canRetry(status)).toBe(false)
    }
    for (const status of ['done', 'failed', 'dead_letter', 'cancelled'] as const) {
      expect(canRetry(status)).toBe(true)
    }
  })

  it('offers the three set-status targets bar the current one', () => {
    // 04 gives `set_status` no precondition, so the drawer offers all
    // three; writing a status onto itself is not an operation.
    expect(statusTargets('failed')).toEqual([...STATUS_TARGETS])
    expect(statusTargets('cancelled')).toEqual(['ready', 'dead_letter'])
    expect(statusTargets('ready')).toEqual(['cancelled', 'dead_letter'])
  })

  it('labels a status as a person writes it', () => {
    expect(statusLabel('dead_letter')).toBe('dead letter')
    expect(statusLabel('ready')).toBe('ready')
  })
})

describe('the drawer’s formatting', () => {
  it('prints a value as indented JSON, and nothing as null', () => {
    expect(jsonBlock({ node: 'qa' })).toBe('{\n  "node": "qa"\n}')
    expect(jsonBlock(null)).toBe('null')
    expect(jsonBlock(undefined)).toBe('null')
  })

  it('says where a priority came from', () => {
    expect(priorityLine(6, true)).toBe('6 · declared on the node')
    expect(priorityLine(0, false)).toBe('0 · the workflow’s default')
  })

  it('has no timestamp for a time that has not happened', () => {
    expect(stamp(null)).toBeUndefined()
    expect(stamp(undefined)).toBeUndefined()
    expect(stamp('')).toBeUndefined()
    // A string the browser cannot parse is shown as the server sent it,
    // rather than as `Invalid Date`.
    expect(stamp('the day before')).toBe('the day before')
    expect(stamp('2026-09-08T08:00:00Z')).toContain('2026')
  })

  it('lists a stats entry in the order the adapter wrote it', () => {
    expect(
      statsRows({ model: 'sonnet', tokens_in: 612, cost_usd: 0.42 }, formatValue),
    ).toEqual([
      ['model', 'sonnet'],
      ['tokens_in', '612'],
      ['cost_usd', '0.42'],
    ])
    expect(statsRows(null, formatValue)).toEqual([])
  })
})

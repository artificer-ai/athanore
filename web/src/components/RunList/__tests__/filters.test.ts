import { describe, expect, it } from 'vitest'

import type { RunSummary } from '../../../api/gen/types.gen'
import { EMPTY_RUN_FILTER, NO_NODE_FILTER, type RunFilter } from '../../../store/ui'
import {
  RUN_STATUSES,
  activeCount,
  choiceOptions,
  clearColumn,
  columnActive,
  parseLocal,
  passes,
  toLocalInput,
  toggled,
  workflowCounts,
} from '../filters'

const NOW = Date.parse('2026-09-26T12:00:00')
const HOUR = 3_600_000

function summary(over: Partial<RunSummary> = {}): RunSummary {
  return {
    id: '01K5AAAA',
    workflow: 'feature_build',
    title: 'rebuild run detail',
    status: 'completed',
    position: 1,
    created: new Date(NOW - 2 * HOUR).toISOString(),
    updated: new Date(NOW - HOUR).toISOString(),
    ...over,
  }
}

function filter(over: Partial<RunFilter> = {}): RunFilter {
  return { ...EMPTY_RUN_FILTER, ...over }
}

const RUNS: RunSummary[] = [
  summary({ id: 'A', status: 'running', current_nodes: ['review'] }),
  summary({ id: 'B', status: 'running', current_nodes: ['engineering', 'qa'] }),
  summary({ id: 'C', status: 'failed', workflow: 'gamedev' }),
  summary({ id: 'D', status: 'completed', created: new Date(NOW - 3 * 86_400_000).toISOString() }),
]

describe('passes', () => {
  it('passes everything through an empty filter', () => {
    expect(RUNS.every((run) => passes(run, EMPTY_RUN_FILTER, NOW))).toBe(true)
  })

  it('matches STATUS as any of the chosen statuses', () => {
    const f = filter({ statuses: ['failed', 'completed'] })
    expect(RUNS.filter((run) => passes(run, f, NOW)).map((run) => run.id)).toEqual([
      'C',
      'D',
    ])
  })

  it('matches NODE when any node the run is in was chosen', () => {
    const f = filter({ nodes: ['qa'] })
    expect(RUNS.filter((run) => passes(run, f, NOW)).map((run) => run.id)).toEqual(['B'])
  })

  it('matches `(none)` to a run in no node', () => {
    const f = filter({ nodes: [NO_NODE_FILTER] })
    expect(RUNS.filter((run) => passes(run, f, NOW)).map((run) => run.id)).toEqual([
      'C',
      'D',
    ])
  })

  it('keeps a rolling window relative to now', () => {
    const f = filter({ within: 24 * HOUR })
    expect(passes(RUNS[0]!, f, NOW)).toBe(true)
    expect(passes(RUNS[3]!, f, NOW)).toBe(false)
    // Twenty-three hours on, the two-hour-old run has left the window.
    expect(passes(RUNS[0]!, f, NOW + 23 * HOUR)).toBe(false)
  })

  it('keeps the whole of the TO minute', () => {
    const run = summary({ created: '2026-09-26T10:05:40' })
    expect(passes(run, filter({ before: '2026-09-26T10:05' }), NOW)).toBe(true)
    expect(passes(run, filter({ before: '2026-09-26T10:04' }), NOW)).toBe(false)
    expect(passes(run, filter({ after: '2026-09-26T10:06' }), NOW)).toBe(false)
    expect(passes(run, filter({ after: '2026-09-26T10:05' }), NOW)).toBe(true)
  })

  it('lets a run of unknown age through only while AGE is off', () => {
    const run = summary({ created: 'not a date' })
    expect(passes(run, EMPTY_RUN_FILTER, NOW)).toBe(true)
    expect(passes(run, filter({ within: 30 * 86_400_000 }), NOW)).toBe(false)
  })

  it('leaves out the one column it is told to, for faceting', () => {
    const f = filter({ statuses: ['failed'], workflows: ['feature_build'] })
    expect(passes(RUNS[2]!, f, NOW)).toBe(false)
    expect(passes(RUNS[2]!, f, NOW, 'workflow')).toBe(true)
  })
})

describe('choiceOptions', () => {
  it('offers every status of 03, counted over the other columns', () => {
    const options = choiceOptions('status', RUNS, filter({ workflows: ['feature_build'] }), NOW)

    expect(options.map((option) => option.value)).toEqual(RUN_STATUSES)
    expect(Object.fromEntries(options.map((option) => [option.value, option.count]))).toEqual({
      queued: 0,
      running: 2,
      paused: 0,
      completed: 1,
      failed: 0,
      cancelled: 0,
    })
  })

  it('does not count its own column against its choices', () => {
    const options = choiceOptions('status', RUNS, filter({ statuses: ['failed'] }), NOW)

    expect(options.find((option) => option.value === 'running')).toMatchObject({
      count: 2,
      on: false,
    })
    expect(options.find((option) => option.value === 'failed')).toMatchObject({
      count: 1,
      on: true,
    })
  })

  it('offers the nodes runs are in, by name, with `(none)` last', () => {
    const options = choiceOptions('node', RUNS, EMPTY_RUN_FILTER, NOW)

    expect(options.map((option) => option.label)).toEqual([
      'engineering',
      'qa',
      'review',
      '(none)',
    ])
    expect(options.at(-1)!.count).toBe(2)
  })

  it('offers the workflows runs are of, by name, counted over the other columns', () => {
    const options = choiceOptions('workflow', RUNS, filter({ statuses: ['failed'] }), NOW)

    expect(options.map((option) => [option.value, option.count])).toEqual([
      ['feature_build', 0],
      ['gamedev', 1],
    ])
  })

  it('keeps a chosen node no run is in any more, so it can be turned off', () => {
    const options = choiceOptions('node', RUNS, filter({ nodes: ['gone'] }), NOW)

    expect(options.find((option) => option.value === 'gone')).toMatchObject({
      count: 0,
      on: true,
    })
  })
})

describe('the filter record', () => {
  it('counts the columns that filter, the workflow marks as one', () => {
    expect(activeCount(EMPTY_RUN_FILTER)).toBe(0)
    expect(
      activeCount(filter({ workflows: ['a', 'b'], title: 'x', after: '2026-09-01T00:00' })),
    ).toBe(3)
  })

  it('treats blank text as off', () => {
    expect(columnActive(filter({ id: '  ' }), 'id')).toBe(false)
  })

  it('clears one column and leaves the rest', () => {
    const f = filter({ within: HOUR, before: '2026-09-01T00:00', title: 'x' })
    expect({ ...f, ...clearColumn('age') }).toEqual(filter({ title: 'x' }))
  })

  it('counts runs per workflow over every other column', () => {
    const counts = workflowCounts(RUNS, filter({ statuses: ['running', 'failed'], workflows: ['gamedev'] }), NOW)
    expect(Object.fromEntries(counts)).toEqual({ feature_build: 2, gamedev: 1 })
  })

  it('toggles a value in and out of a list', () => {
    expect(toggled(['a'], 'b')).toEqual(['a', 'b'])
    expect(toggled(['a', 'b'], 'a')).toEqual(['b'])
  })

  it('round-trips a local datetime to the minute', () => {
    const value = toLocalInput(NOW)
    expect(value).toBe('2026-09-26T12:00')
    expect(parseLocal(value)).toBe(NOW)
    expect(parseLocal('')).toBeNull()
    expect(parseLocal('garbage')).toBeNull()
  })
})

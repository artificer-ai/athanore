import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { listRunsApiRunsGetQueryKey } from '../../../api/gen/@tanstack/react-query.gen'
import type { RunSummary } from '../../../api/gen/types.gen'
import { queryKeys } from '../../../realtime/invalidate'
import { ALL_WORKFLOWS, useUi } from '../../../store/ui'
import { useRunListModel, useRuns } from '../useRunList'

function summary(over: Partial<RunSummary> = {}): RunSummary {
  return {
    id: '01JD5XABCDEFGHJKMNPQRSTVWX',
    workflow: 'feature_build',
    title: 'rebuild run detail',
    status: 'completed',
    position: 1,
    created: '2026-09-08T08:00:00Z',
    updated: '2026-09-08T08:30:00Z',
    ...over,
  }
}

const RUNS: RunSummary[] = [
  summary({ id: 'aaaa1111', title: 'squirrels vs chipmunks', workflow: 'gamedev' }),
  summary({
    id: 'bbbb2222',
    title: 'rebuild run detail',
    workflow: 'feature_build',
    status: 'running',
    current_nodes: ['engineering'],
  }),
  summary({ id: 'cccc3333', title: 'append log', workflow: 'feature_build' }),
]

/** The model, rendered as text a test can read. */
function Probe() {
  const model = useRunListModel()
  return (
    <>
      <span data-testid="ids">{model.rows.map((row) => row.id).join(',')}</span>
      <span data-testid="total">{String(model.total)}</span>
      <span data-testid="active">{String(model.active)}</span>
      <span data-testid="workflows">{model.workflows.join(',')}</span>
      <span data-testid="pending">{String(model.isPending)}</span>
    </>
  )
}

/** A query client holding `runs`, or nothing at all when given `null`. */
function seeded(runs: RunSummary[] | null = RUNS): QueryClient {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { staleTime: 5000, retry: false } },
  })
  if (runs !== null) {
    queryClient.setQueryData(listRunsApiRunsGetQueryKey(), runs)
  }
  return queryClient
}

function probe(queryClient: QueryClient = seeded()) {
  return render(
    <QueryClientProvider client={queryClient}>
      <Probe />
    </QueryClientProvider>,
  )
}

function shown(): string[] {
  const ids = screen.getByTestId('ids').textContent ?? ''
  return ids === '' ? [] : ids.split(',')
}

describe('useRuns', () => {
  it('reads the cache entry the invalidation table refreshes', () => {
    // The key is the generated one on both sides, so `run.*`/`task.*`
    // reach exactly the entry the list draws from (10 §Realtime).
    expect(listRunsApiRunsGetQueryKey()).toEqual(queryKeys.runs())
  })

  it('is the generated query, `queryFn` and all', () => {
    const queryClient = seeded()
    function Reader() {
      const { data } = useRuns()
      return <span data-testid="count">{data?.length ?? -1}</span>
    }
    render(
      <QueryClientProvider client={queryClient}>
        <Reader />
      </QueryClientProvider>,
    )

    expect(screen.getByTestId('count')).toHaveTextContent('3')
  })
})

describe('useRunListModel', () => {
  beforeEach(() => {
    useUi.setState({ runFilter: { workflow: ALL_WORKFLOWS, query: '' } })
  })

  it('shows every run in the order the server sent them', () => {
    probe()

    expect(shown()).toEqual(['aaaa1111', 'bbbb2222', 'cccc3333'])
    expect(screen.getByTestId('total')).toHaveTextContent('3')
  })

  it('counts the runs in progress for the header', () => {
    probe()

    expect(screen.getByTestId('active')).toHaveTextContent('1')
  })

  it('omits the counts until the server has answered', () => {
    probe(seeded(null))

    expect(screen.getByTestId('total')).toHaveTextContent('null')
    expect(screen.getByTestId('active')).toHaveTextContent('null')
    expect(screen.getByTestId('pending')).toHaveTextContent('true')
  })

  it('offers one chip per workflow there are runs of, by name', () => {
    probe()

    expect(screen.getByTestId('workflows')).toHaveTextContent('feature_build,gamedev')
  })

  it('narrows to one workflow when a chip is on', () => {
    probe()

    act(() => useUi.getState().setRunWorkflow('feature_build'))
    expect(shown()).toEqual(['bbbb2222', 'cccc3333'])

    act(() => useUi.getState().setRunWorkflow(ALL_WORKFLOWS))
    expect(shown()).toHaveLength(3)
  })

  it('narrows on the title', () => {
    probe()

    act(() => useUi.getState().setRunQuery('SQUIRRELS'))
    expect(shown()).toEqual(['aaaa1111'])
  })

  it('narrows on the id', () => {
    probe()

    act(() => useUi.getState().setRunQuery('cccc'))
    expect(shown()).toEqual(['cccc3333'])
  })

  it('narrows on the chip and the query together', () => {
    probe()

    act(() => useUi.getState().setRunWorkflow('feature_build'))
    act(() => useUi.getState().setRunQuery('append'))
    expect(shown()).toEqual(['cccc3333'])
  })

  it('treats a blank query as no filter at all', () => {
    probe()

    act(() => useUi.getState().setRunQuery('   '))
    expect(shown()).toHaveLength(3)
  })

  it('re-reads the clock so the AGE column does not go stale', () => {
    // Ten seconds after the fixtures were created, so the first render
    // is a number the tick has somewhere to move from.
    vi.useFakeTimers({ now: Date.parse('2026-09-08T08:00:10Z') })
    try {
      const queryClient = seeded()
      function Age() {
        const model = useRunListModel()
        return <span data-testid="age">{model.rows[0]?.age}</span>
      }
      render(
        <QueryClientProvider client={queryClient}>
          <Age />
        </QueryClientProvider>,
      )
      expect(screen.getByTestId('age')).toHaveTextContent('10s')

      act(() => {
        vi.advanceTimersByTime(2 * 60 * 1000)
      })

      expect(screen.getByTestId('age')).toHaveTextContent('2m')
    } finally {
      vi.useRealTimers()
    }
  })
})

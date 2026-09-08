import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import {
  getGraphApiRunsRunIdGraphGetQueryKey,
  listRunsApiRunsGetQueryKey,
  manifestApiPluginsGetQueryKey,
} from '../../api/gen/@tanstack/react-query.gen'
import type { GraphOut, PluginManifestEntry, RunSummary } from '../../api/gen/types.gen'
import { cardsOf, panesOf, usePanes } from '../usePanes'
import {
  BUILTIN_ENTRY,
  GAMEDEV_ENTRY,
  MANIFEST,
  OTHER_ENTRY,
  graph,
} from './fixtures'

const RUN: RunSummary = {
  id: 'run-gamedev',
  workflow: 'gamedev',
  title: 'squirrels vs chipmunks',
  status: 'running',
  position: 1,
  created: '2026-09-08T08:00:00Z',
  updated: '2026-09-08T08:30:00Z',
}

const OTHER_RUN: RunSummary = {
  ...RUN,
  id: 'run-feature',
  workflow: 'feature_build',
}

const NONE: ReadonlySet<string> = new Set()

/** The names of the panes `panesOf` returns, which is the cycle order. */
function names(
  manifest: readonly PluginManifestEntry[],
  scope: { runId: string | undefined; workflow: string | undefined },
  live: ReadonlySet<string> = NONE,
): string[] {
  return panesOf(manifest, scope, live).map((pane) => pane.name)
}

describe('panesOf', () => {
  it('puts the builtins first, then the run workflow’s own panes', () => {
    expect(names(MANIFEST, { runId: RUN.id, workflow: 'gamedev' })).toEqual([
      'overview',
      'log',
      'agent',
      'requests',
      'graph',
      'words',
      'sessions',
    ])
  })

  it('leaves out another workflow’s panes: scope follows ownership', () => {
    const panes = names(MANIFEST, { runId: OTHER_RUN.id, workflow: 'feature_build' })

    expect(panes).toContain('diff')
    expect(panes).not.toContain('words')
    expect(panes).not.toContain('sessions')
  })

  it('leaves out `placement="card"` panels: those append to the overview', () => {
    expect(names(MANIFEST, { runId: RUN.id, workflow: 'gamedev' })).not.toContain(
      'budget',
    )
  })

  it('shows a node-slot pane only while that node is live', () => {
    const scope = { runId: RUN.id, workflow: 'gamedev' }

    expect(names(MANIFEST, scope, new Set(['engineering']))).not.toContain('playfield')
    expect(names(MANIFEST, scope, new Set(['qa']))).toContain('playfield')
  })

  it('shows the global panes, of every workflow, when no run is selected', () => {
    expect(names(MANIFEST, { runId: undefined, workflow: undefined })).toEqual([
      'inbox',
      'leaderboard',
    ])
  })

  it('shows the builtin panes for a run whose workflow is not known yet', () => {
    // `?run=` names a run the run list has not answered for. It is still
    // a run: the builtins apply to every one of them (09 §Context).
    expect(names(MANIFEST, { runId: RUN.id, workflow: undefined })).toEqual([
      'overview',
      'log',
      'agent',
      'requests',
      'graph',
    ])
  })

  it('reads the manifest’s order rather than one of its own', () => {
    const reversed = [GAMEDEV_ENTRY, BUILTIN_ENTRY]

    expect(names(reversed, { runId: RUN.id, workflow: 'gamedev' })).toEqual([
      'words',
      'sessions',
      'overview',
      'log',
      'agent',
      'requests',
      'graph',
    ])
  })
})

describe('cardsOf', () => {
  it('is the `placement="card"` panels of the run’s own workflow', () => {
    const cards = cardsOf(MANIFEST, { runId: RUN.id, workflow: 'gamedev' })

    expect(cards.map((card) => card.id)).toEqual(['gamedev:budget'])
  })

  it('leaves out a card of a workflow this run is not of', () => {
    expect(cardsOf(MANIFEST, { runId: OTHER_RUN.id, workflow: 'feature_build' })).toEqual(
      [],
    )
  })

  it('is empty with no run: there is no overview to append to', () => {
    expect(cardsOf(MANIFEST, { runId: undefined, workflow: undefined })).toEqual([])
  })
})

/** A cache holding the manifest, the run list and one run's graph. */
function seeded(over: { manifest?: PluginManifestEntry[]; graph?: GraphOut } = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { staleTime: 60_000, retry: false } },
  })
  queryClient.setQueryData(manifestApiPluginsGetQueryKey(), over.manifest ?? MANIFEST)
  queryClient.setQueryData(listRunsApiRunsGetQueryKey(), [RUN, OTHER_RUN])
  queryClient.setQueryData(
    getGraphApiRunsRunIdGraphGetQueryKey({ path: { run_id: RUN.id } }),
    over.graph ?? graph([]),
  )
  return queryClient
}

/**
 * The model, rendered as text, with its actions on buttons.
 *
 * The actions are exercised by clicking rather than by holding the model
 * in a variable: `usePanes` exposes them so that the bar, the dots and
 * T067's keymap all move one piece of state, and a button is what each
 * of those is.
 */
function Probe({
  runId,
  index,
  onChange,
}: {
  runId: string | undefined
  index: number | undefined
  onChange: (index: number) => void
}) {
  const panes = usePanes(runId, { index, onChange })
  return (
    <>
      <span data-testid="label">{panes.label}</span>
      <span data-testid="index">{String(panes.index)}</span>
      <span data-testid="current">{panes.current?.name ?? ''}</span>
      <span data-testid="names">{panes.panes.map((p) => p.name).join(',')}</span>
      <span data-testid="run-id">{panes.runId ?? ''}</span>
      <span data-testid="run-workflow">{panes.run?.workflow ?? ''}</span>
      <button type="button" onClick={panes.prev}>
        prev
      </button>
      <button type="button" onClick={panes.next}>
        next
      </button>
      {JUMPS.map((to) => (
        <button key={to} type="button" onClick={() => panes.jump(to)}>
          {`jump ${String(to)}`}
        </button>
      ))}
    </>
  )
}

/** The jumps the tests make: one in range, and two out of it. */
const JUMPS = [3, 8, -1]

function mount(
  runId: string | undefined,
  index: number | undefined,
  over: Parameters<typeof seeded>[0] = {},
) {
  const onChange = vi.fn()
  const result = render(
    <QueryClientProvider client={seeded(over)}>
      <Probe runId={runId} index={index} onChange={onChange} />
    </QueryClientProvider>,
  )
  return { onChange, ...result }
}

describe('usePanes', () => {
  it('labels the pane the mock’s way: NAME (i/n)', () => {
    mount(RUN.id, 1)

    expect(screen.getByTestId('label')).toHaveTextContent('LOG (2/7)')
    expect(screen.getByTestId('current')).toHaveTextContent('log')
  })

  it('clamps the index when the new selection has fewer panes', () => {
    // Six panes on a gamedev run, five plus `diff` on a feature_build
    // one: the index the operator was on has to survive the move and
    // land on a pane that exists.
    mount(OTHER_RUN.id, 6)

    expect(screen.getByTestId('names')).toHaveTextContent(
      'overview,log,agent,requests,graph,diff',
    )
    expect(screen.getByTestId('index')).toHaveTextContent('5')
    expect(screen.getByTestId('current')).toHaveTextContent('diff')
  })

  it('clamps to zero when there is nothing to show', () => {
    mount(undefined, 4, { manifest: [] })

    expect(screen.getByTestId('index')).toHaveTextContent('0')
    expect(screen.getByTestId('label')).toHaveTextContent('—')
    expect(screen.getByTestId('current')).toBeEmptyDOMElement()
  })

  it('wraps at both ends of the cycle', async () => {
    const { onChange } = mount(RUN.id, 6)

    await userEvent.click(screen.getByRole('button', { name: 'next' }))
    expect(onChange).toHaveBeenLastCalledWith(0)

    onChange.mockClear()
    await userEvent.click(screen.getByRole('button', { name: 'prev' }))
    expect(onChange).toHaveBeenLastCalledWith(5)
  })

  it('wraps backwards from the first pane to the last', async () => {
    const { onChange } = mount(RUN.id, 0)

    await userEvent.click(screen.getByRole('button', { name: 'prev' }))
    expect(onChange).toHaveBeenLastCalledWith(6)
  })

  it('jumps to a pane that exists and ignores one that does not', async () => {
    const { onChange } = mount(RUN.id, 0)

    await userEvent.click(screen.getByRole('button', { name: 'jump 3' }))
    expect(onChange).toHaveBeenLastCalledWith(3)

    onChange.mockClear()
    await userEvent.click(screen.getByRole('button', { name: 'jump 8' }))
    await userEvent.click(screen.getByRole('button', { name: 'jump -1' }))
    expect(onChange).not.toHaveBeenCalled()
  })

  it('adds a node pane once the graph reports the node live', () => {
    mount(RUN.id, 0, { graph: graph(['qa']) })

    expect(screen.getByTestId('names')).toHaveTextContent('playfield')
  })

  it('leaves the node pane out while the node is not live', () => {
    mount(RUN.id, 0, { graph: graph(['engineering']) })

    expect(screen.getByTestId('names')).not.toHaveTextContent('playfield')
  })

  it('shows the global panes with no run selected', () => {
    mount(undefined, 0)

    expect(screen.getByTestId('names')).toHaveTextContent('inbox,leaderboard')
    expect(screen.getByTestId('label')).toHaveTextContent('INBOX (1/2)')
  })

  it('reports the run row for the pane bar’s status pill', () => {
    mount(RUN.id, 0)

    expect(screen.getByTestId('run-workflow')).toHaveTextContent('gamedev')
    expect(screen.getByTestId('run-id')).toHaveTextContent(RUN.id)
  })

  it('does not stop existing because a workflow declares no panes', () => {
    mount(RUN.id, 0, { manifest: [OTHER_ENTRY] })

    expect(screen.getByTestId('names')).toBeEmptyDOMElement()
    expect(screen.getByTestId('index')).toHaveTextContent('0')
  })
})

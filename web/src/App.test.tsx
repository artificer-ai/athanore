import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import {
  listRunsApiRunsGetQueryKey,
  manifestApiPluginsGetQueryKey,
} from './api/gen/@tanstack/react-query.gen'
import type { PluginManifestEntry, RunSummary } from './api/gen/types.gen'
import type { AppSearch } from './routes/search'
import { DEFAULT_LIST_WIDTH, usePrefs } from './store/prefs'
import { ALL_WORKFLOWS, useUi } from './store/ui'

const RUNS: RunSummary[] = [
  {
    id: 'aaaa1111bbbb',
    workflow: 'feature_build',
    title: 'rebuild run detail',
    status: 'running',
    position: 1,
    current_nodes: ['engineering'],
    created: '2026-09-08T08:56:00Z',
    updated: '2026-09-08T08:59:00Z',
  },
  {
    id: 'cccc3333dddd',
    workflow: 'gamedev',
    title: 'squirrels vs chipmunks',
    status: 'completed',
    position: 2,
    created: '2026-09-01T08:00:00Z',
    updated: '2026-09-01T09:00:00Z',
  },
]

/** The two builtin panes a pane bar has something to cycle with. */
const MANIFEST: PluginManifestEntry[] = [
  {
    workflow: '_builtin',
    panels: [
      { name: 'overview', slot: 'run', placement: 'pane', scope: 'run', kind: 'custom' },
      { name: 'log', slot: 'run', placement: 'pane', scope: 'run', kind: 'custom' },
    ],
  },
]

/**
 * The shell over a seeded cache.
 *
 * `staleTime` keeps the seeded entries fresh, so nothing here reaches
 * for the network: the fetches behind `GET /api/runs` and
 * `GET /api/plugins` are the generated client's and are exercised where
 * they belong (`api/__tests__`, `panes/__tests__`).
 */
function shell(
  search: AppSearch = {},
  over: { runs?: RunSummary[]; onSelectRun?: (runId: string) => void } = {},
) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { staleTime: 5000, retry: false } },
  })
  queryClient.setQueryData(listRunsApiRunsGetQueryKey(), over.runs ?? RUNS)
  queryClient.setQueryData(manifestApiPluginsGetQueryKey(), MANIFEST)

  return render(
    <QueryClientProvider client={queryClient}>
      <App
        search={search}
        onSelectRun={over.onSelectRun ?? (() => {})}
        onSelectPane={() => {}}
        onOpenPalette={() => {}}
      />
    </QueryClientProvider>,
  )
}

function rows() {
  return within(screen.getByRole('listbox', { name: 'run rows' })).queryAllByRole(
    'option',
  )
}

describe('App', () => {
  beforeEach(() => {
    usePrefs.setState({ listWidth: DEFAULT_LIST_WIDTH, listCollapsed: false })
    useUi.setState({
      focus: 'list',
      runFilter: { workflow: ALL_WORKFLOWS, query: '' },
    })
  })

  it('renders the four regions of 10 §Layout', () => {
    shell()

    expect(screen.getByRole('banner')).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'runs' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'detail' })).toBeInTheDocument()
    expect(screen.getByRole('contentinfo')).toBeInTheDocument()
  })

  it('hangs the list and the detail pane off the splitter', () => {
    shell()

    // The width between them is the splitter's, and so is the rail; the
    // shell only says which side each region goes.
    expect(screen.getByTestId('list-panel')).toContainElement(
      screen.getByRole('region', { name: 'runs' }),
    )
    expect(screen.getByTestId('detail-panel')).toContainElement(
      screen.getByRole('region', { name: 'detail' }),
    )
    expect(screen.getByRole('separator', { name: 'resize run list' })).toBeInTheDocument()
  })

  it('shows the rail in place of the list when it is collapsed', () => {
    usePrefs.setState({ listCollapsed: true })
    shell()

    expect(screen.queryByRole('region', { name: 'runs' })).toBeNull()
    expect(screen.getByRole('button', { name: 'show run list' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'detail' })).toBeInTheDocument()
  })

  it('counts the rows on screen in the strip and the header', () => {
    shell()

    expect(screen.getByTestId('rows-shown')).toHaveTextContent('2 shown')
    expect(screen.getByTestId('run-count')).toHaveTextContent('2 runs')
    expect(screen.getByTestId('active-count')).toHaveTextContent('1 active')
  })

  it('counts them in the collapsed rail too', () => {
    usePrefs.setState({ listCollapsed: true })
    shell()

    expect(screen.getByTestId('runs-rail')).toHaveTextContent('RUNS 2')
  })

  it('narrows the rows as the header’s `/` input is typed into', () => {
    shell()
    expect(rows()).toHaveLength(2)

    // `fireEvent`, not `userEvent`: jsdom performs no layout, so every
    // element's box is 0×0 at the origin and the resizable group reads a
    // pointer press anywhere as a press on its handle, taking the focus
    // the keystrokes would have gone to. Typing itself is exercised on
    // `RunFilters`, which has no splitter beside it.
    fireEvent.change(screen.getByRole('textbox', { name: 'filter runs' }), {
      target: { value: 'squirrels' },
    })

    expect(rows()).toHaveLength(1)
    expect(rows()[0]).toHaveTextContent('squirrels vs chipmunks')
    expect(screen.getByTestId('rows-shown')).toHaveTextContent('1 shown')
    // The header's count is the server's, not the filter's.
    expect(screen.getByTestId('run-count')).toHaveTextContent('2 runs')
  })

  it('narrows the rows from a workflow chip', async () => {
    shell()

    await userEvent.click(screen.getByRole('radio', { name: 'gamedev' }))

    expect(rows()).toHaveLength(1)
    expect(rows()[0]).toHaveTextContent('squirrels vs chipmunks')
  })

  it('draws the run `?run=` names as the selected one', () => {
    shell({ run: 'cccc3333dddd' })

    expect(rows()[0]).toHaveAttribute('aria-selected', 'false')
    expect(rows()[1]).toHaveAttribute('aria-selected', 'true')
  })

  it('hands a clicked row to the route, which writes `?run=`', async () => {
    const onSelectRun = vi.fn()
    shell({}, { onSelectRun })

    await userEvent.click(rows()[0]!)
    expect(onSelectRun).toHaveBeenCalledWith('aaaa1111bbbb')
  })

  it('passes the selected run through to the pane bar', () => {
    shell({ run: 'a4c81f20b91e' })

    expect(screen.getByTestId('selected-run')).toHaveTextContent('a4c81f20b91e')
  })

  it('asks for the palette from the footer', async () => {
    const onOpenPalette = vi.fn()
    const queryClient = new QueryClient({
      defaultOptions: { queries: { staleTime: 5000, retry: false } },
    })
    queryClient.setQueryData(listRunsApiRunsGetQueryKey(), RUNS)
    queryClient.setQueryData(manifestApiPluginsGetQueryKey(), MANIFEST)
    render(
      <QueryClientProvider client={queryClient}>
        <App
          search={{}}
          onSelectRun={() => {}}
          onSelectPane={() => {}}
          onOpenPalette={onOpenPalette}
        />
      </QueryClientProvider>,
    )

    await userEvent.click(screen.getByRole('button', { name: /palette/ }))
    expect(onOpenPalette).toHaveBeenCalledOnce()
  })
})

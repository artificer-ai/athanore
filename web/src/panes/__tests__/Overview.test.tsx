/**
 * The overview pane over the two things it reads: the `overview`
 * builtin's route and `GET /api/runs/{id}`.
 *
 * The run detail is seeded into the cache rather than fetched, because
 * what is under test is what the pane *draws* from it — the attempt a
 * NODES row opens, the node the bars call active, the branches OUTPUTS
 * lists — and not the request, which is the generated client's.
 *
 * The suite that matters most here is the last one. 01 §Real data only
 * says an unknown is omitted and never zero-filled, and a pane is where
 * that rule is broken: `0` tokens and `NaN` widths are what a renderer
 * produces when it treats "nothing measured it" as a number.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { getRunApiRunsRunIdGetQueryKey } from '../../api/gen/@tanstack/react-query.gen'
import type { RunDetail } from '../../api/gen/types.gen'
import { createAppQueryClient } from '../../api/client'
import {
  MIN_BAR_PERCENT,
  Overview,
  PREVIEW_LENGTH,
  asOverview,
  formatAbout,
  formatCost,
  formatCount,
  formatSeconds,
  latestTaskOf,
  preview,
  tokenBars,
  type OverviewData,
} from '../kinds'
import {
  FANNED_OUT,
  IDLE_OVERVIEW_SOURCE,
  OVERVIEW_RUN,
  OVERVIEW_SOURCE,
  runDetail,
} from './fixtures'

let queryClient: QueryClient

/** A source answer, narrowed the way the pane host narrows it. */
function narrowed(data: unknown): OverviewData {
  const overview = asOverview(data)
  if (overview === null) throw new Error('the overview fixture no longer narrows')
  return overview
}

function draw(
  data: unknown = OVERVIEW_SOURCE,
  options: { detail?: RunDetail | undefined; onOpenTask?: (taskId: number) => void } = {},
) {
  if (options.detail !== undefined) {
    queryClient.setQueryData(
      getRunApiRunsRunIdGetQueryKey({ path: { run_id: OVERVIEW_RUN } }),
      options.detail,
    )
  }
  return render(
    <QueryClientProvider client={queryClient}>
      <Overview
        data={narrowed(data)}
        runId={OVERVIEW_RUN}
        {...(options.onOpenTask === undefined ? {} : { onOpenTask: options.onOpenTask })}
      />
    </QueryClientProvider>,
  )
}

/** The token bars, in the order they are drawn. */
function bars() {
  return within(screen.getByTestId('token-bars'))
    .getAllByRole('listitem')
    .map((bar) => ({
      node: bar.dataset['node'],
      active: bar.dataset['active'],
      width: bar.querySelector<HTMLElement>('[data-testid="token-bar-fill"]')?.style
        .width,
      count: bar.textContent,
    }))
}

/** One NODES row's cells, as text. */
function rowCells(node: string): string[] {
  const row = screen.getByRole('button', { name: new RegExp(`^${node}`) })
  return [...row.children].map((cell) => cell.textContent ?? '')
}

beforeEach(() => {
  queryClient = createAppQueryClient()
  // The seeded run detail is the whole of what this pane fetches: kept
  // fresh, nothing here reaches for the network.
  queryClient.setDefaultOptions({ queries: { retry: false, staleTime: Infinity } })
  // Except in the one test that seeds nothing, where the pane asks and
  // the server is not there — which is a state it has to draw too.
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async () =>
        new Response(JSON.stringify({ error: 'no such run', code: 'not_found' }), {
          status: 404,
          headers: { 'Content-Type': 'application/json' },
        }),
    ),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('the STATS tiles', () => {
  it('formats each of the four by the field it is', () => {
    draw(OVERVIEW_SOURCE, { detail: runDetail() })

    const tiles = within(screen.getByTestId('metric-grid'))
    expect(tiles.getByText('TOKENS').nextSibling).toHaveTextContent('612,884')
    expect(tiles.getByText('COST').nextSibling).toHaveTextContent('$0.2914')
    expect(tiles.getByText('DURATION').nextSibling).toHaveTextContent('246s')
    expect(tiles.getByText('POSITION').nextSibling).toHaveTextContent('1 of 34')
  })

  it('shows only the tiles the route sent, and invents no zeros', () => {
    draw(IDLE_OVERVIEW_SOURCE, { detail: runDetail({ status: 'queued' }) })

    const tiles = within(screen.getByTestId('metric-grid'))
    expect(tiles.queryByText('TOKENS')).toBeNull()
    expect(tiles.queryByText('COST')).toBeNull()
    expect(tiles.getAllByRole('term')).toHaveLength(2)
  })
})

describe('the token bars', () => {
  it('scales to the largest node and accents the one the run is in', () => {
    draw(OVERVIEW_SOURCE, { detail: runDetail() })

    expect(bars()).toEqual([
      { node: 'prompt', active: 'false', width: '4%', count: 'prompt18,204' },
      { node: 'product', active: 'false', width: '15%', count: 'product61,933' },
      {
        node: 'architecture',
        active: 'false',
        width: '29%',
        count: 'architecture119,447',
      },
      {
        node: 'engineering',
        active: 'true',
        width: '100%',
        count: 'engineering413,300',
      },
    ])
  })

  it('draws no bar for a node no agent reported on', () => {
    draw(OVERVIEW_SOURCE, { detail: runDetail() })

    // `review` has a NODES row and no `tokens` key: a zero-length bar
    // would be this pane claiming it spent nothing (01 §Real data only).
    expect(bars().map((bar) => bar.node)).not.toContain('review')
    expect(screen.getByRole('button', { name: /^review/ })).toBeInTheDocument()
  })

  it('draws none at all before an agent has run', () => {
    draw(IDLE_OVERVIEW_SOURCE, { detail: runDetail({ status: 'queued' }) })

    expect(screen.queryByTestId('token-bars')).toBeNull()
  })
})

describe('the kv meta grid', () => {
  it('draws 10 §Panes’ fields, humanising AGE and cutting SESSION to 8', () => {
    draw(OVERVIEW_SOURCE, { detail: runDetail() })

    const grid = screen.getByTestId('overview-meta')
    const meta = within(grid)
    expect(meta.getByText('RUN').nextSibling).toHaveTextContent(OVERVIEW_RUN)
    expect(meta.getByText('WORKFLOW').nextSibling).toHaveTextContent('feature_build')
    // The run status and the node it is in, joined by the route.
    expect(meta.getByText('STATUS').nextSibling).toHaveTextContent(
      'running · engineering',
    )
    expect(meta.getByText('AGE').nextSibling).toHaveTextContent('4m')
    expect(meta.getByText('SESSION').nextSibling).toHaveTextContent('01a02310')
    expect(meta.getByText('AGENTS').nextSibling).toHaveTextContent('4')
    // …and not the two the grid is the wrong shape for: they are the
    // block's now, which is the whole of this change (15, D208).
    expect(meta.queryByText('TITLE')).toBeNull()
    expect(meta.queryByText('DESCRIPTION')).toBeNull()
    const fields = [...grid.querySelectorAll('dt')].map((key) => key.textContent)
    expect(fields).toEqual(['RUN', 'WORKFLOW', 'STATUS', 'AGE', 'SESSION', 'AGENTS'])
  })

  it('omits SESSION and AGENTS entirely when no agent has run', () => {
    draw(IDLE_OVERVIEW_SOURCE, { detail: runDetail({ status: 'queued' }) })

    const grid = screen.getByTestId('overview-meta')
    const meta = within(grid)
    expect(meta.queryByText('SESSION')).toBeNull()
    expect(meta.queryByText('AGENTS')).toBeNull()
    // …and the fields that are facts about every run are still there.
    expect(meta.getByText('AGE').nextSibling).toHaveTextContent('1m')
    const fields = [...grid.querySelectorAll('dt')].map((key) => key.textContent)
    expect(fields).toEqual(['RUN', 'WORKFLOW', 'STATUS', 'AGE'])
  })

  it('is not drawn at all for a source whose meta held only those two', () => {
    // The grid's guard is `Object.keys(meta).length > 0`, and after the
    // move a meta of TITLE and DESCRIPTION formats to nothing — so the
    // pane draws no section rather than `KvPane`'s "nothing to show".
    draw({
      ...OVERVIEW_SOURCE,
      meta: { TITLE: 'only a title', DESCRIPTION: 'and a description' },
    })

    expect(screen.queryByTestId('overview-meta')).toBeNull()
    expect(screen.getByTestId('overview-about')).toBeInTheDocument()
  })
})

describe('the title and description block', () => {
  it('draws both, labelled, from what the route sent', () => {
    draw(OVERVIEW_SOURCE, { detail: runDetail() })

    const about = within(screen.getByTestId('overview-about'))
    expect(about.getByText('TITLE').nextSibling).toHaveTextContent(
      'Rebuild run detail as a web pane set',
    )
    // Whole: the block is a layout, and nothing about the values changed.
    expect(about.getByText('DESCRIPTION').nextSibling).toHaveTextContent(
      'Port the TUI pane cycle to the web app.',
    )
  })

  it('is a dl of its own, and its rows are not the grid’s', () => {
    draw(OVERVIEW_SOURCE, { detail: runDetail() })

    const block = screen.getByTestId('overview-about')
    // Not `KvPane`: the whole point is that these two are out of the
    // 240 px grid, so the block cannot be that grid drawn twice.
    expect(within(block).queryByTestId('pane-kv')).toBeNull()
    const lists = block.querySelectorAll('dl')
    expect(lists).toHaveLength(1)
    // Each key is a term and its value the description of it — the same
    // pairing `KvPane` and the OUTPUTS list announce, one axis turned.
    for (const key of block.querySelectorAll('dt')) {
      expect(key.nextElementSibling?.tagName).toBe('DD')
    }
  })

  it('sits under the meta grid and above NODES', () => {
    const { container } = draw(OVERVIEW_SOURCE, { detail: runDetail() })

    const sections = [...container.querySelectorAll('section')].map(
      (section) =>
        section.dataset['testid'] ?? section.getAttribute('aria-label') ?? '',
    )
    expect(sections).toEqual(['STATS', 'overview-meta', 'overview-about', 'NODES'])
  })

  it('keeps DESCRIPTION as a dash for a run that has none', () => {
    // 10 §Panes: "DESCRIPTION is the run's, or `—`" — the one field the
    // block draws whether or not the route sent it, and the route sends
    // it only for a run the operator wrote one for.
    draw(IDLE_OVERVIEW_SOURCE, { detail: runDetail({ status: 'queued' }) })

    const about = within(screen.getByTestId('overview-about'))
    expect(about.getByText('TITLE').nextSibling).toHaveTextContent('append log')
    expect(about.getByText('DESCRIPTION').nextSibling).toHaveTextContent('—')
    // …and the grid has no DESCRIPTION key at all any more.
    const grid = within(screen.getByTestId('overview-meta'))
    expect(grid.queryByText('DESCRIPTION')).toBeNull()
  })

  it('drops the TITLE row when the source sent no title', () => {
    // An absent field is absent, not dashed: 10 gives the dash to
    // DESCRIPTION and to nothing else.
    draw({
      ...OVERVIEW_SOURCE,
      meta: { RUN: OVERVIEW_RUN, DESCRIPTION: 'only a description' },
    })

    const about = within(screen.getByTestId('overview-about'))
    expect(about.queryByText('TITLE')).toBeNull()
    expect(about.getByText('DESCRIPTION').nextSibling).toHaveTextContent(
      'only a description',
    )
  })

  it('is absent entirely when the source sent neither', () => {
    // An `overview`-kind panel a plugin declares need not be about a run
    // at all, and two dashes under it would be invented (01 §Real data).
    draw({ ...OVERVIEW_SOURCE, meta: { RUN: OVERVIEW_RUN, WORKFLOW: 'w' } })

    expect(screen.queryByTestId('overview-about')).toBeNull()
    const grid = within(screen.getByTestId('overview-meta'))
    expect(grid.getByText('RUN').nextSibling).toHaveTextContent(OVERVIEW_RUN)
    expect(grid.getByText('WORKFLOW').nextSibling).toHaveTextContent('w')
  })

  it('does not cut a long description', () => {
    // The block has the pane's width so a paragraph can use it; a clamp
    // on the way there would undo the whole change.
    const description = `${'a description far past the preview limit. '.repeat(8)}end.`
    expect(description.length).toBeGreaterThan(PREVIEW_LENGTH)
    draw({
      ...OVERVIEW_SOURCE,
      meta: { ...OVERVIEW_SOURCE.meta, DESCRIPTION: description },
    })

    expect(
      within(screen.getByTestId('overview-about')).getByText('DESCRIPTION').nextSibling,
    ).toHaveTextContent(description)
  })
})

describe('the NODES table', () => {
  it('draws one row per node, in the order the run entered them', () => {
    draw(OVERVIEW_SOURCE, { detail: runDetail() })

    const rows = within(screen.getByTestId('node-rows')).getAllByRole('button')
    expect(rows.map((row) => row.dataset['node'])).toEqual([
      'prompt',
      'product',
      'architecture',
      'engineering',
      'review',
    ])
  })

  it('formats each cell by the kind its column declared', () => {
    draw(OVERVIEW_SOURCE, { detail: runDetail() })

    expect(rowCells('engineering')).toEqual([
      'engineering',
      '2',
      'in_progress',
      '413,300',
      '105s',
    ])
    // A node with no stats entry shows `—`, not `0` (01 §Real data only).
    expect(rowCells('review')).toEqual(['review', '1', 'ready', '—', '—'])
    expect(rowCells('prompt')[4]).toBe('9.2s')
  })

  it('opens the node’s most recent attempt in the task drawer', async () => {
    const user = userEvent.setup()
    const onOpenTask = vi.fn()
    draw(OVERVIEW_SOURCE, { detail: runDetail(), onOpenTask })

    await user.click(screen.getByRole('button', { name: /^engineering/ }))

    // Two attempts of `engineering`; the drawer opens on the later one,
    // which is the attempt the row's STATUS is about.
    expect(onOpenTask).toHaveBeenCalledWith(405)
  })

  it('does not offer a row whose attempts have not arrived yet', () => {
    draw(OVERVIEW_SOURCE, { onOpenTask: vi.fn() })

    expect(screen.getByRole('button', { name: /^engineering/ })).toBeDisabled()
  })
})

describe('the OUTPUTS list', () => {
  it('is drawn only when more than one branch terminated', () => {
    draw(OVERVIEW_SOURCE, { detail: runDetail({ outputs: FANNED_OUT }) })

    const outputs = within(screen.getByTestId('overview-outputs'))
    expect(outputs.getByText('render [0: alpha]')).toBeInTheDocument()
    expect(outputs.getByText('render [1: beta]')).toBeInTheDocument()
    expect(outputs.getByText('{"frames":240,"crashes":0}')).toBeInTheDocument()
    expect(outputs.getByText('beta ran clean')).toBeInTheDocument()
  })

  it('is absent for a run that ended in one terminal task', () => {
    draw(OVERVIEW_SOURCE, {
      detail: runDetail({ outputs: FANNED_OUT.slice(0, 1) }),
    })

    // One terminal task is `RunDetail.output`; a list of one is not a
    // per-branch view of anything (04 §Routing edge cases).
    expect(screen.queryByTestId('overview-outputs')).toBeNull()
  })

  it('is absent for a run that has not finished', () => {
    draw(OVERVIEW_SOURCE, { detail: runDetail() })

    expect(screen.queryByTestId('overview-outputs')).toBeNull()
  })
})

describe('a run nothing has measured', () => {
  it('renders whole, with no zeros and no NaN', () => {
    const { container } = draw(IDLE_OVERVIEW_SOURCE, {
      detail: runDetail({ status: 'queued', current_nodes: [], tasks: [] }),
    })

    const text = container.textContent ?? ''
    expect(text).not.toContain('NaN')
    expect(text).not.toContain('undefined')
    // The only digits on the pane are the ones the route sent: the
    // duration, the position, the attempt count and the age.
    expect(text).not.toMatch(/\$0\.0000/)
    expect(screen.getByTestId('pane-overview')).toBeInTheDocument()
    expect(rowCells('prompt')).toEqual(['prompt', '1', 'ready', '—', '—'])
  })

  it('says so rather than drawing an empty NODES frame', () => {
    draw(
      { ...IDLE_OVERVIEW_SOURCE, table: { ...IDLE_OVERVIEW_SOURCE.table, rows: [] } },
      { detail: runDetail({ status: 'queued', tasks: [] }) },
    )

    expect(screen.getByRole('status')).toHaveTextContent('no attempts yet')
  })
})

describe('the field rules', () => {
  it('never prints a span, a count or a cost it was not given', () => {
    // The route omits the key rather than sending `0` or `null`, and
    // `—` is what the app shows for a fact nobody has (01 §Real data).
    expect(formatSeconds(undefined)).toBe('—')
    expect(formatCount(null)).toBe('—')
    expect(formatCost(undefined)).toBe('—')
    // …and it does not round a real measurement away either.
    expect(formatSeconds(0.42)).toBe('0.4s')
    expect(formatSeconds(3944.2)).toBe('3944s')
    expect(formatCost(0)).toBe('$0.0000')
  })

  it('gives every bar the same width when every node spent the same', () => {
    const rows = [
      { node: 'a', tokens: 0 },
      { node: 'b', tokens: 0 },
    ]

    // Nothing is divided by the largest total when it is zero: two
    // nodes that really reported `0` get the minimum bar, not `NaN%`.
    expect(tokenBars(rows, []).map((bar) => bar.percent)).toEqual([
      MIN_BAR_PERCENT,
      MIN_BAR_PERCENT,
    ])
  })

  it('cuts a long output value to a preview', () => {
    expect(preview('x'.repeat(200))).toHaveLength(PREVIEW_LENGTH + 1)
    expect(preview('a\n  b')).toBe('a b')
  })

  it('reads TITLE and DESCRIPTION out of the meta, or neither', () => {
    // The block's whole reading rule: the dash belongs to DESCRIPTION,
    // an absent title drops its row, and a meta with neither key draws
    // no block rather than two invented fields.
    expect(formatAbout({})).toBeNull()
    expect(formatAbout({ RUN: OVERVIEW_RUN })).toBeNull()
    expect(formatAbout({ TITLE: 'a title' })).toEqual({
      title: 'a title',
      description: '—',
    })
    expect(formatAbout({ DESCRIPTION: 'a description' })).toEqual({
      title: null,
      description: 'a description',
    })
    expect(formatAbout({ TITLE: 'a title', DESCRIPTION: 'a description' })).toEqual({
      title: 'a title',
      description: 'a description',
    })
  })

  it('finds the latest attempt of a node, and none for one with no row', () => {
    const tasks = runDetail().tasks

    expect(latestTaskOf(tasks, 'engineering')).toBe(405)
    expect(latestTaskOf(tasks, 'gate')).toBeUndefined()
    expect(latestTaskOf(undefined, 'engineering')).toBeUndefined()
  })
})

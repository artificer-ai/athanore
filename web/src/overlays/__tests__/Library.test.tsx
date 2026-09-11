/**
 * `Library`: the mock's panel, the source behind its right-hand column,
 * and the anchor `open definition` lands on (`overlays/Library.tsx`).
 *
 * Two things this suite insists on beyond "it rendered":
 *
 * - **which element the anchor scrolled to.** A viewer that drew the
 *   right file and left the operator at line 1 has done the part of
 *   `open definition` nobody asked for, so `scrollIntoView` is spied on
 *   and the element it was called on is asserted by its `data-line`.
 * - **that the source came off the wire for the workflow that was
 *   picked.** The requests are recorded, because a panel that reused the
 *   first workflow's text under the second's name looks identical to one
 *   that fetched.
 *
 * The highlighter is mocked. jsdom resolves no cascade, so a coloured
 * span proves nothing about colour — what matters here is that the lines
 * and their anchors are the same elements before and after shiki
 * arrives, and one test drives it to make sure the tokens land on them.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import type { ThemedToken } from 'shiki'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createAppQueryClient } from '../../api/client'
import type { RunSummary, SourceOut, WorkflowOut } from '../../api/gen/types.gen'
import { Library, LIBRARY_GLOSS, LIBRARY_TITLE } from '../Library'

const { tokenize } = vi.hoisted(() => ({
  tokenize: vi.fn<(code: string, lang: string) => Promise<ThemedToken[][] | null>>(),
}))
vi.mock('../../lib/highlight', () => ({ tokenize }))

/** One registered workflow, as `GET /api/workflows` sends it. */
function workflow(name: string, nodes: string[]): WorkflowOut {
  return {
    name,
    start: nodes[0] ?? '',
    capacity: 1,
    in_flight: 0,
    nodes: Object.fromEntries(
      nodes.map((node) => [
        node,
        { edges: [], generation: 0, label: node, join: false },
      ]),
    ),
    plugin: { panels: [], actions: [] },
    pool: 'default',
  }
}

/** One run of `wf`, as the run list holds it. */
function run(id: string, wf: string): RunSummary {
  return {
    id,
    workflow: wf,
    title: id,
    status: 'completed',
    position: 1,
    created: '2026-09-08T08:00:00Z',
    updated: '2026-09-08T08:01:00Z',
  }
}

const WORKFLOWS = [
  workflow('feature_build', ['prompt', 'review']),
  workflow('gamedev', ['design']),
]

const RUNS = [
  run('aaaa1111', 'feature_build'),
  run('bbbb2222', 'gamedev'),
  run('cccc3333', 'feature_build'),
]

/**
 * The module `feature_build` is defined in, line for line:
 *
 * ```
 * 1  import athanore
 * 2
 * 3  wf = athanore.Workflow("feature_build")
 * 4
 * 5  @wf.node(entry=True)
 * 6  def prompt(ctx):
 * 7      return ctx.expand(ctx.run.description)
 * 8
 * 9  @wf.node(after="prompt")
 * 10 def review(ctx):
 * 11     return ctx.agent("review")
 * ```
 */
const FEATURE_SOURCE: SourceOut = {
  file: '/srv/workflows/feature_build.py',
  source: [
    'import athanore',
    '',
    'wf = athanore.Workflow("feature_build")',
    '',
    '@wf.node(entry=True)',
    'def prompt(ctx):',
    '    return ctx.expand(ctx.run.description)',
    '',
    '@wf.node(after="prompt")',
    'def review(ctx):',
    '    return ctx.agent("review")',
    '',
  ].join('\n'),
  nodes: { prompt: { line: 5 }, review: { line: 9 } },
}

const GAMEDEV_SOURCE: SourceOut = {
  file: '/srv/workflows/gamedev.py',
  source: [
    'import athanore',
    '',
    '@wf.node(entry=True)',
    'def design(ctx):',
    '    pass',
    '',
  ].join('\n'),
  nodes: { design: { line: 3 } },
}

/** What the fake server answers with, per route. */
type Reply = { status: number; body: unknown }

const SOURCES: Record<string, Reply> = {
  feature_build: { status: 200, body: FEATURE_SOURCE },
  gamedev: { status: 200, body: GAMEDEV_SOURCE },
}

/** Every URL the panel asked for, in order. */
let asked: string[]

/**
 * A server holding the two workflows, three runs and both modules.
 *
 * `sources` overrides one workflow's answer, which is how the 404 of a
 * workflow whose source Python cannot produce is exercised.
 */
function stubServer(
  over: { workflows?: Reply; runs?: Reply; sources?: Record<string, Reply> } = {},
) {
  asked = []
  const sources = { ...SOURCES, ...over.sources }

  vi.stubGlobal(
    'fetch',
    vi.fn((request: Request) => {
      asked.push(request.url)

      const source = /\/api\/workflows\/([^/]+)\/source/.exec(request.url)
      const reply =
        source !== null
          ? (sources[source[1] ?? ''] ?? {
              status: 404,
              body: { error: 'no such workflow' },
            })
          : request.url.includes('/api/runs')
            ? (over.runs ?? { status: 200, body: RUNS })
            : (over.workflows ?? { status: 200, body: WORKFLOWS })

      return Promise.resolve(
        new Response(JSON.stringify(reply.body), {
          status: reply.status,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
    }),
  )
}

let queryClient: QueryClient

/** The overlay over the button that opens it, which `esc` restores to. */
function Harness({
  runId,
  node,
  onClose,
}: {
  runId: string | undefined
  node: string | undefined
  onClose: () => void
}) {
  const [open, setOpen] = useState(false)

  return (
    <QueryClientProvider client={queryClient}>
      <button type="button" onClick={() => setOpen(true)}>
        open library
      </button>
      <Library
        open={open}
        runId={runId}
        node={node}
        onClose={() => {
          setOpen(false)
          onClose()
        }}
      />
    </QueryClientProvider>
  )
}

/**
 * Draw the shell, and hold on to the button that opens the overlay.
 *
 * The opener is read here rather than in each test because a modal
 * dialog marks the rest of the document `aria-hidden`, so once the
 * overlay is up it cannot be found by role at all.
 */
function draw(over: { runId?: string; node?: string } = {}) {
  const user = userEvent.setup()
  const onClose = vi.fn()
  render(<Harness runId={over.runId} node={over.node} onClose={onClose} />)
  return {
    user,
    onClose,
    opener: screen.getByRole('button', { name: 'open library' }),
  }
}

/** ...and open it, waiting for the source column the two queries unlock. */
async function open(over: { runId?: string; node?: string } = {}) {
  const shell = draw(over)
  await shell.user.click(shell.opener)
  await screen.findByTestId('library-source')
  return shell
}

/** The line elements the viewer drew, in file order. */
function lines(): HTMLElement[] {
  return Array.from(
    screen.getByTestId('library-source').querySelectorAll<HTMLElement>('[data-line]'),
  )
}

/** Every element `scrollIntoView` was called on, in order. */
let scrolled: Element[]

beforeEach(() => {
  queryClient = createAppQueryClient()
  queryClient.setDefaultOptions({
    queries: { retry: false, staleTime: Infinity },
    mutations: { retry: false },
  })
  tokenize.mockResolvedValue(null)
  scrolled = []
  vi.spyOn(Element.prototype, 'scrollIntoView').mockImplementation(function (
    this: Element,
  ) {
    scrolled.push(this)
  })
  stubServer()
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  tokenize.mockReset()
})

describe('Library', () => {
  it('is the mock’s panel: the header, the list and the viewer', async () => {
    await open()

    const panel = screen.getByRole('dialog', { name: LIBRARY_TITLE })
    expect(within(panel).getByText(LIBRARY_GLOSS)).toBeInTheDocument()
    expect(within(panel).getByText('esc close')).toBeInTheDocument()
    // The mock's "hot-reloaded from workflows/" is a claim v1 does not
    // make: reload is a restart (D35).
    expect(panel.textContent).not.toContain('hot-reloaded')

    const rows = within(screen.getByRole('listbox', { name: 'workflows' })).getAllByRole(
      'option',
    )
    expect(rows.map((row) => row.getAttribute('data-workflow'))).toEqual([
      'feature_build',
      'gamedev',
    ])
    // `name · n nodes` over `k runs · file`, counted off the run list
    // the app already holds.
    expect(rows[0]).toHaveTextContent('feature_build')
    expect(rows[0]).toHaveTextContent('2 nodes')
    expect(rows[0]).toHaveTextContent('2 runs · /srv/workflows/feature_build.py')
    expect(rows[1]).toHaveTextContent('1 run · /srv/workflows/gamedev.py')
  })

  it('opens on the selected run’s workflow and draws its module', async () => {
    await open({ runId: 'bbbb2222' })

    expect(screen.getByRole('option', { name: /gamedev/ })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    const viewer = screen.getByTestId('library-source')
    expect(within(viewer).getByText('/srv/workflows/gamedev.py')).toBeInTheDocument()
    expect(viewer).toHaveTextContent('def design(ctx):')
  })

  it('loads the source of the workflow that was selected', async () => {
    const { user } = await open({ runId: 'bbbb2222' })

    await user.click(screen.getByRole('option', { name: /feature_build/ }))

    await waitFor(() => {
      expect(screen.getByTestId('library-source')).toHaveTextContent(
        'def prompt(ctx):',
      )
    })
    expect(screen.getByTestId('library-source')).toHaveTextContent(
      '/srv/workflows/feature_build.py',
    )
    // The text came off the wire under that workflow's own name.
    expect(
      asked.some((url) => url.endsWith('/api/workflows/feature_build/source')),
    ).toBe(true)
  })

  it('hangs an anchor on every line, and names the node that starts one', async () => {
    await open({ runId: 'aaaa1111' })

    const drawn = lines()
    // Eleven lines: the module's trailing newline is not a twelfth.
    expect(drawn).toHaveLength(11)
    expect(drawn[0]).toHaveTextContent('import athanore')
    expect(drawn[4]).toHaveAttribute('data-node', 'prompt')
    expect(drawn[8]).toHaveAttribute('data-node', 'review')
    expect(drawn[5]).not.toHaveAttribute('data-node')
  })

  it('lands on the node’s line, not merely on the file', async () => {
    await open({ runId: 'aaaa1111', node: 'review' })

    // `?node=review` is line 9 of that module, which is the `@wf.node`
    // the body carries — the element scrolled to, and the one drawn as
    // the anchor.
    expect(scrolled.at(-1)).toHaveAttribute('data-line', '9')
    expect(scrolled.at(-1)).toHaveAttribute('data-node', 'review')
    expect(
      screen.getByTestId('library-source').querySelectorAll('[data-anchor="true"]'),
    ).toHaveLength(1)
    expect(
      screen.getByTestId('library-source').querySelector('[data-anchor="true"]'),
    ).toHaveAttribute('data-line', '9')
  })

  it('opens at the top when the node is not defined in this file', async () => {
    // A body imported from another module is left out of `nodes` (08
    // §Workflows); there is no line to land on and none is invented.
    await open({ runId: 'aaaa1111', node: 'imported' })

    expect(scrolled).toHaveLength(0)
    expect(
      screen.getByTestId('library-source').querySelector('[data-anchor="true"]'),
    ).toBeNull()
  })

  it('drops the anchor when the operator picks another workflow', async () => {
    const { user } = await open({ runId: 'aaaa1111', node: 'review' })
    expect(scrolled).toHaveLength(1)

    await user.click(screen.getByRole('option', { name: /gamedev/ }))

    await waitFor(() => {
      expect(screen.getByTestId('library-source')).toHaveTextContent('def design(ctx):')
    })
    // `?node=` named a node of the run's graph, not of this file.
    expect(scrolled).toHaveLength(1)
    expect(
      screen.getByTestId('library-source').querySelector('[data-anchor="true"]'),
    ).toBeNull()
  })

  it('colours the same lines the anchors are on, once shiki answers', async () => {
    tokenize.mockResolvedValue([
      [{ content: 'import', offset: 0, color: '#ff7b72', fontStyle: 2 }],
      [{ content: '', offset: 7 }],
    ])

    await open({ runId: 'aaaa1111', node: 'review' })

    const first = await waitFor(() => {
      const token = lines()[0]?.querySelector('span')
      expect(token).not.toBeNull()
      return token!
    })
    expect(first).toHaveStyle({ color: 'rgb(255, 123, 114)', fontWeight: 'bold' })
    // The anchor is still on the element it was on before the tokens
    // arrived, and the line the highlighter never reached is its text.
    expect(lines()[8]).toHaveAttribute('data-anchor', 'true')
    expect(lines()[8]).toHaveTextContent('@wf.node(after="prompt")')
  })

  it('says what the server said when a workflow has no source', async () => {
    stubServer({
      sources: {
        gamedev: {
          status: 404,
          body: {
            error: 'no source is available for workflow: exec()',
            code: 'not_found',
          },
        },
      },
    })

    const shell = draw({ runId: 'bbbb2222' })
    await shell.user.click(shell.opener)

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'no source is available for workflow: exec()',
    )
    // The row still lists the workflow; only its file is unknown.
    expect(screen.getByRole('option', { name: /gamedev/ })).toHaveTextContent('1 run')
    expect(screen.getByRole('option', { name: /gamedev/ }).textContent).not.toContain(
      '.py',
    )
  })

  it('says a server with nothing registered runs no workflows', async () => {
    stubServer({ workflows: { status: 200, body: [] } })
    const shell = draw()

    await shell.user.click(shell.opener)

    expect(await screen.findByTestId('library-notice')).toHaveTextContent(
      'no workflows are registered',
    )
  })

  it('says so rather than drawing a library it could not read', async () => {
    stubServer({ workflows: { status: 500, body: { error: 'boom' } } })
    const shell = draw()

    await shell.user.click(shell.opener)

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'the workflows could not be read',
    )
  })

  it('counts no runs rather than zero when the run list could not be read', async () => {
    stubServer({ runs: { status: 500, body: { error: 'boom' } } })
    await open()

    const row = screen.getByRole('option', { name: /feature_build/ })
    expect(row).toHaveTextContent('/srv/workflows/feature_build.py')
    expect(row.textContent).not.toContain('runs')
  })

  it('stacks its two columns into a sheet below the breakpoint', async () => {
    await open()

    // jsdom resolves no cascade, so what a unit can assert here is the
    // declaration and not the geometry: that the body says "two columns
    // at `md`, two rows below it" in one place, and that the sheet has
    // dropped its margin. Whether the panel then fits a 390 px screen is
    // Playwright's (`web/e2e/mobile.spec.ts`).
    const body = screen.getByRole('listbox', { name: 'workflows' }).parentElement
    expect(body).toHaveClass('grid-cols-[230px_minmax(0,1fr)]')
    expect(body).toHaveClass('max-md:grid-cols-1')
    expect(body).toHaveClass('max-md:grid-rows-[minmax(0,40%)_minmax(0,60%)]')

    const panel = screen.getByRole('dialog', { name: LIBRARY_TITLE })
    expect(panel).toHaveClass('max-md:inset-0')
    expect(panel).toHaveClass('max-md:h-auto')
    expect(panel).toHaveClass('max-md:w-full')
    expect(panel).toHaveClass('max-md:rounded-none')
    // A full-screen sheet leaves no backdrop to tap, so it carries a
    // real close button (21 §Overlays, narrow).
    expect(within(panel).getByRole('button', { name: 'close' })).toBeInTheDocument()
  })

  it('closes on esc, and gives focus back to what opened it', async () => {
    const { user, onClose, opener } = await open({ runId: 'aaaa1111' })

    // The caret is on the selected workflow, which is where an operator
    // arrows on from.
    expect(document.activeElement).toHaveAttribute('data-workflow', 'feature_build')

    await user.keyboard('{Escape}')

    expect(onClose).toHaveBeenCalledOnce()
    await waitFor(() => {
      expect(document.activeElement).toBe(opener)
    })
  })
})

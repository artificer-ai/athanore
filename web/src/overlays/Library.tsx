/**
 * The workflow library overlay (`w`, the palette's `open workflow
 * library`, and the graph pane's `open definition`): the Python a
 * workflow is defined in, read in the app (`docs/v1/10-frontend.md`
 * §Overlays, D35).
 *
 * The mock's panel: `WORKFLOW LIBRARY · defined in python` over a
 * 230 px left list — `name · n nodes` and `k runs · file` — and a source
 * viewer beside it. The mock's second clause, "hot-reloaded from
 * `workflows/`", is deliberately not written: v1 requires a restart, and
 * hot reload is a later seam (D35). The viewer is the valuable part.
 *
 * **This is read-only, and it is where "the signature is the graph"
 * becomes legible** to somebody who did not write the workflow. Nothing
 * here edits, and nothing here parses: the per-node line numbers are the
 * route's own, computed with `inspect` (`GET /api/workflows/{name}/source`,
 * 08 §Workflows), so the app never has to know what a decorator looks
 * like.
 *
 * **The anchor is `?node=`.** The app's search carries the node it has
 * in focus — the graph pane writes it when a row is clicked (10 §Graph
 * pane) — so `open definition` needs to hand nothing extra over: the
 * overlay opens on the selected run's workflow and scrolls to that
 * node's `def`. A node the file does not define has no line to land on
 * (a body imported from another module, 08 §Workflows) and the viewer
 * opens at the top, which is the honest answer.
 *
 * **Four requests, three of them entries the app already holds.** The
 * workflows are the New Run overlay's list; the runs are the list on the
 * left of the app, counted here rather than asked for per workflow; and
 * a workflow's source is the entry the graph pane's SOURCE line already
 * reads, so `open definition` opens on text that is usually in hand. The
 * fourth is the rest of the library's sources, asked for together
 * (`useQueries`) because `file` is on the left list's row and the wire
 * carries it nowhere else.
 *
 * **Highlighting is shiki's tokens, drawn by this file** (`lib/highlight.ts`).
 * Not shiki's HTML: every line here is an anchor, carrying its number
 * and the node whose body starts on it, so the lines have to be elements
 * this viewer made. Until the highlighter arrives — and for good if the
 * chunk fails — the same lines are drawn uncoloured, so the source and
 * its anchors are on screen either way and nothing waits on a
 * highlighter.
 *
 * The focus round trip is the palette's and the new-run overlay's, for
 * their reason (`./Palette.tsx`, `./NewRun.tsx`): this dialog opens from
 * `?overlay=library` and has no `Dialog.Trigger`, so Radix would hand
 * focus back to `<body>`. The caret goes to the selected workflow's row,
 * which is where an operator arrows on from, and the same two mount
 * orders are handled the same two ways.
 */
import { useQueries, useQuery } from '@tanstack/react-query'
import { Dialog } from 'radix-ui'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ThemedToken } from 'shiki'

import {
  getSourceApiWorkflowsNameSourceGetOptions,
  listWorkflowsApiWorkflowsGetOptions,
} from '../api/gen/@tanstack/react-query.gen'
import type { RunSummary, SourceOut, WorkflowOut } from '../api/gen/types.gen'
import { useRuns } from '../components/RunList'
import { useKeyOwner } from '../keys'
import { actionError } from '../lib/errors'
import { tokenize } from '../lib/highlight'
import { cn } from '../lib/utils'
import { OverlayClose } from './OverlayPanel'
import {
  anchorLine,
  initialSelection,
  libraryRows,
  plural,
  rowDetail,
  scrollToLine,
  sourceLines,
  tokenStyle,
} from './library'

/** The dialog's accessible name, and the mock's header kicker. */
export const LIBRARY_TITLE = 'workflow library'

/** The mock's second header word, without its hot-reload claim (D35). */
export const LIBRARY_GLOSS = 'defined in python'

/** What the viewer highlights. Every workflow is a Python module. */
const LANGUAGE = 'python'

/** The id the open-focus lands on: the selected workflow's row. */
const SELECTED_ROW_ID = 'library-selected-workflow'

/**
 * `GET /api/workflows/{name}/source` for every workflow at once.
 *
 * One entry per workflow, and they are the generated query's own keys —
 * the same entries the graph pane's SOURCE line fills — so the library
 * and the pane never hold two copies of a module. `retry: false` for the
 * pane's reason: a workflow whose source Python cannot produce is a 404
 * and an answer, not a fault (08 §Workflows).
 */
function useSources(workflows: readonly WorkflowOut[]) {
  return useQueries({
    queries: workflows.map((workflow) => {
      const { queryFn, ...options } = getSourceApiWorkflowsNameSourceGetOptions({
        path: { name: workflow.name },
      })
      return { ...options, queryFn: queryFn!, retry: false }
    }),
  })
}

export function Library({
  open,
  runId,
  node,
  onClose,
}: {
  open: boolean
  /** `?run=`: whose workflow the library opens on (10 §Graph pane). */
  runId?: string | undefined
  /** `?node=`: the node in focus, and the line to land on. */
  node?: string | undefined
  onClose: () => void
}) {
  // An open overlay owns the keyboard: while it is up the app's global
  // map is off, so a `d` in here cannot reach the delete confirm
  // (`keys/scope.ts`, 10 §Keyboard).
  useKeyOwner(open)

  const restoreFocusTo = useRef<HTMLElement | null>(null)
  const panel = useRef<HTMLDivElement | null>(null)
  // Whether the dialog's open-focus has already run: it is what tells a
  // list mounting later that the caret is its to take. See `./NewRun.tsx`
  // for why the two orders are handled as two.
  const opened = useRef(false)

  // Stable: the list runs it from an effect keyed on it.
  const settleFocus = useCallback(() => {
    if (opened.current) document.getElementById(SELECTED_ROW_ID)?.focus()
  }, [])

  return (
    <Dialog.Root
      open={open}
      onOpenChange={(next) => {
        // `esc`, the backdrop and a click outside all arrive here, so
        // there is one way out and the app writes `?overlay=` away once.
        if (!next) onClose()
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay
          data-testid="library-backdrop"
          className="fixed inset-0 z-40 bg-[rgba(10,11,18,.72)]"
        />

        <Dialog.Content
          ref={panel}
          data-testid="library"
          // The panel says what it is in two words and describes nothing
          // further; without this Radix warns about the description it
          // cannot find.
          aria-describedby={undefined}
          onOpenAutoFocus={(event) => {
            // The last moment at which the element the operator was on
            // is still the focused one.
            event.preventDefault()
            restoreFocusTo.current =
              document.activeElement instanceof HTMLElement
                ? document.activeElement
                : null
            opened.current = true
            const row = document.getElementById(SELECTED_ROW_ID)
            if (row !== null) row.focus()
            else panel.current?.focus()
          }}
          onCloseAutoFocus={(event) => {
            // Radix's own restore goes to a trigger this dialog has not
            // got, which is `<body>` — the operator's place in the app,
            // lost. Ours goes back where focus came from.
            event.preventDefault()
            restoreFocusTo.current?.focus()
            restoreFocusTo.current = null
            opened.current = false
          }}
          className="text-body fixed top-1/2 left-1/2 z-50 flex h-[min(640px,88vh)] w-[min(880px,96vw)] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-lg border border-[var(--color-neutral-800)] bg-[var(--color-surface)] text-foreground shadow-[var(--shadow-lg)] max-md:inset-0 max-md:h-auto max-md:w-full max-md:max-w-none max-md:translate-x-0 max-md:translate-y-0 max-md:rounded-none"
        >
          <div className="flex flex-none items-center gap-[10px] border-b border-[var(--color-neutral-900)] px-[14px] py-[10px]">
            <Dialog.Title className="text-kicker text-[var(--color-accent-300)]">
              {LIBRARY_TITLE}
            </Dialog.Title>
            <span className="text-hint text-[var(--color-neutral-500)]">
              {LIBRARY_GLOSS}
            </span>
            <div className="flex-1" />
            <span className="text-hint text-muted-foreground max-md:hidden">
              esc close
            </span>
            <OverlayClose />
          </div>

          <LibraryBody
            runId={runId}
            node={node}
            onListMounted={settleFocus}
          />
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

/** A line of prose where the panel's two columns would be. */
function Notice({ children, alert }: { children: string; alert?: boolean }) {
  return (
    <p
      data-testid="library-notice"
      {...(alert === true ? { role: 'alert' } : { role: 'status' })}
      className="text-meta px-[14px] py-[14px] text-muted-foreground"
    >
      {children}
    </p>
  )
}

/**
 * The workflows and the runs, and what the panel is until both have
 * arrived.
 *
 * The three states below the query are three different things and none
 * of them is a library: nothing to list yet, a server that could not be
 * asked, and a server that runs no workflows at all.
 */
function LibraryBody({
  runId,
  node,
  onListMounted,
}: {
  runId: string | undefined
  node: string | undefined
  onListMounted: () => void
}) {
  // `queryFn` is put back explicitly for the reason `useRuns` does it
  // (`components/RunList/useRunList.ts`): the generator declares it
  // optional and `exactOptionalPropertyTypes` will not assign an
  // optional-and-absent property onto `useQuery`'s required one.
  const { queryFn, ...options } = listWorkflowsApiWorkflowsGetOptions()
  const workflows = useQuery({ ...options, queryFn: queryFn! })
  // The run list this app already holds. A run count is a fact about
  // those rows, and the selected run's workflow is on one of them, so
  // neither costs a request of its own.
  const runs = useRuns()

  if (workflows.isError) {
    return <Notice alert>the workflows could not be read</Notice>
  }
  // The runs are waited for as well, because two things on this panel
  // are facts about them: the run count on every row, and which workflow
  // the overlay opens on. A library drawn before they arrive would count
  // none and open on the wrong one.
  if (workflows.isPending || runs.isPending) {
    return <Notice>loading the library…</Notice>
  }
  if (workflows.data.length === 0) {
    return <Notice>no workflows are registered</Notice>
  }

  return (
    <LibraryPanel
      workflows={workflows.data}
      // `undefined` and not an empty list: a run list that could not be
      // read is not a server with no runs, and the rows say neither
      // rather than counting zero (01 §Real data only).
      runs={runs.data}
      runId={runId}
      node={node}
      onMounted={onListMounted}
    />
  )
}

/** The left list and the viewer, over the workflows the server sent. */
function LibraryPanel({
  workflows,
  runs,
  runId,
  node,
  onMounted,
}: {
  workflows: readonly WorkflowOut[]
  /** The run list, or `undefined` when it could not be read. */
  runs: readonly RunSummary[] | undefined
  runId: string | undefined
  node: string | undefined
  /** Say so once, so the caret can be settled ({@link Library}). */
  onMounted: () => void
}) {
  const sources = useSources(workflows)

  // The selection is the overlay's own and not the URL's: `?overlay=`
  // says which overlay is up, and reading a second workflow's source is
  // browsing inside it rather than a view of the app worth linking to.
  // A fresh open is a fresh selection, which is what the dialog's
  // unmount-while-closed already gives us.
  const [selection, setSelection] = useState(() =>
    initialSelection(workflows, runs?.find((run) => run.id === runId)?.workflow, node),
  )

  useEffect(() => {
    onMounted()
  }, [onMounted])

  const files = new Map<string, string>()
  workflows.forEach((workflow, index) => {
    const file = sources[index]?.data?.file
    if (file !== undefined) files.set(workflow.name, file)
  })
  const rows = libraryRows(workflows, runs, files)

  const chosen = workflows.findIndex((workflow) => workflow.name === selection.workflow)
  const source = chosen < 0 ? undefined : sources[chosen]

  return (
    // The columns are classes and not an inline style so that the
    // breakpoint can turn them into rows: below `md` the sheet stacks —
    // the workflow list over the source viewer, each scrolling on its
    // own (21 §Overlays, narrow).
    <div className="grid min-h-0 flex-1 grid-cols-[230px_minmax(0,1fr)] max-md:grid-cols-1 max-md:grid-rows-[minmax(0,40%)_minmax(0,60%)]">
      <div
        role="listbox"
        aria-label="workflows"
        data-testid="library-list"
        className="min-h-0 overflow-auto border-r border-[var(--color-neutral-900)] max-md:border-r-0 max-md:border-b"
      >
        {rows.map((row) => {
          const selected = row.name === selection.workflow
          const detail = rowDetail(row)
          return (
            <button
              key={row.name}
              type="button"
              role="option"
              aria-selected={selected}
              data-selected={selected}
              data-workflow={row.name}
              {...(selected ? { id: SELECTED_ROW_ID } : {})}
              onClick={() => {
                // A workflow the operator picked is not the one the
                // anchor was about, so the anchor goes with it and the
                // viewer opens at the top of the new file.
                setSelection({ workflow: row.name, anchor: undefined })
              }}
              className={cn(
                'block w-full cursor-pointer border-b border-[var(--color-neutral-900)] px-[12px] py-[8px] text-left hover:bg-[var(--color-neutral-900)]',
                selected && 'bg-[var(--color-neutral-900)]',
              )}
            >
              <span className="flex items-baseline gap-[8px]">
                <span className="truncate text-[var(--color-neutral-300)]">
                  {row.name}
                </span>
                <span className="text-hint whitespace-nowrap text-[var(--color-neutral-500)]">
                  {plural(row.nodes, 'node')}
                </span>
              </span>
              {detail !== undefined && (
                <span className="text-hint mt-[2px] block [overflow-wrap:anywhere] text-[var(--color-neutral-500)]">
                  {detail}
                </span>
              )}
            </button>
          )
        })}
      </div>

      {source === undefined ? (
        <Notice>select a workflow to read its definition</Notice>
      ) : source.isPending ? (
        <Notice>loading the source…</Notice>
      ) : source.isError ? (
        <Notice alert>
          {actionError(
            source.error,
            'this server cannot show the source of this workflow',
          )}
        </Notice>
      ) : (
        <SourceView
          // Remounted per workflow: the highlighted tokens and the
          // scroll position belong to the file, not to the column.
          key={selection.workflow}
          source={source.data}
          anchor={selection.anchor}
        />
      )}
    </div>
  )
}

/**
 * One module, line by line, with an anchor on each.
 *
 * The lines are drawn plain and coloured in place when shiki's tokens
 * arrive; the anchors do not move between the two, so a `data-line` the
 * scroll lands on before the highlighter is the same element after it.
 */
function SourceView({
  source,
  anchor,
}: {
  source: SourceOut
  anchor: string | undefined
}) {
  const viewport = useRef<HTMLPreElement | null>(null)
  const [tokens, setTokens] = useState<ThemedToken[][] | null>(null)

  const lines = useMemo(
    () => sourceLines(source.source, source.nodes),
    [source.source, source.nodes],
  )
  const landing = anchorLine(source, anchor)

  useEffect(() => {
    let live = true
    void tokenize(source.source, LANGUAGE).then((coloured) => {
      if (live && coloured !== null) setTokens(coloured)
    })
    return () => {
      live = false
    }
  }, [source.source])

  // Once the lines are on screen, and again if the anchor moves. The
  // highlighter is deliberately not a dependency: it recolours the
  // elements that are already there, and scrolling again when it lands
  // would undo an operator who had scrolled away in the meantime.
  useEffect(() => {
    scrollToLine(viewport.current, landing)
  }, [landing, lines])

  return (
    <div data-testid="library-source" className="flex min-h-0 flex-col">
      {/* Above the scroller, which is where the mock does not put it:
          the mock never scrolls anywhere but the top, and an anchor that
          lands halfway down a module would otherwise take the one line
          saying which module it is off the screen with it. */}
      <p className="text-hint flex-none [overflow-wrap:anywhere] px-[14px] pt-[12px] pb-[8px] tracking-[0.14em] text-[var(--color-neutral-500)]">
        {source.file}
      </p>
      <pre
        ref={viewport}
        className="text-row m-0 min-h-0 flex-1 overflow-auto px-[14px] pb-[14px] leading-[1.65] whitespace-pre-wrap [overflow-wrap:anywhere] text-[var(--color-neutral-300)]"
      >
        <code>
          {lines.map((line) => {
            const landed = line.line === landing
            // The highlighter's tokens for this line, if it has arrived
            // and split the file the same way. A line it did not reach
            // is drawn as its own text, which is what every line is
            // until the chunk lands.
            const coloured = tokens?.[line.line - 1]
            return (
              <span
                key={line.line}
                data-line={line.line}
                data-anchor={landed}
                {...(line.node === undefined ? {} : { 'data-node': line.node })}
                className={cn(
                  'block min-h-[1lh] border-l-2 border-l-transparent pl-[6px]',
                  landed &&
                    'border-l-[var(--color-accent)] bg-[color-mix(in_srgb,var(--color-accent)_14%,transparent)]',
                )}
              >
                {coloured === undefined
                  ? line.text
                  : coloured.map((token) => (
                      <span key={token.offset} style={tokenStyle(token)}>
                        {token.content}
                      </span>
                    ))}
              </span>
            )
          })}
        </code>
      </pre>
    </div>
  )
}

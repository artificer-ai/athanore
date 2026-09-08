/**
 * The event log pane: what happened to a run, in one list, and the one
 * place an operator writes into it (`docs/v1/10-frontend.md` §Panes item
 * 2, and the mock's `isLog` block in `docs/v1/design/Athanore.dc.html`).
 *
 * `EVENT LOG · n lines · ● tailing/○ complete` over `time · source ·
 * message` rows, a `?node=` filter the graph pane links into, and a
 * composer that appends a note.
 *
 * **The merge is the server's.** The rows are the work log and the
 * lifecycle events already merged by time — one route,
 * `athanore/plugins/builtin/log.py`, which is the only place that can
 * tie-break an entry against the event announcing it and the only place
 * that knows which events this pane hides (`task.stream`,
 * `submission.*`, `request.*`, `log.appended`, `agent.stats`). This pane
 * keeps no list of its own and accumulates nothing: it narrows and
 * orders what the source answered with, per render, and a new line
 * arrives the way every other change does — `log.appended` and `task.*`
 * invalidate the panel's query (10 §Realtime and caching).
 *
 * Two things it draws that a plugin's `log` panel does not:
 *
 * - **markdown, for what an agent or a person wrote.** Those are the
 *   entries 10 gives the default tone; an engine line and every
 *   lifecycle sentence is drawn as text, so neither can smuggle
 *   formatting into the pane (`./log.ts`).
 * - **`● tailing` / `○ complete`**, which is the run's status and not
 *   the scroller's: a running run is still producing lines. Whether the
 *   view is *following* the end is the scroller's own business, and
 *   scrolling up to read something does not make the run complete. A
 *   status that has not arrived draws neither word: unknown is omitted.
 */
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'

import { appendLogApiRunsRunIdLogPostMutation } from '../../api/gen/@tanstack/react-query.gen'
import { useRuns } from '../../components/RunList'
import { cn } from '../../lib/utils'
import { useUi } from '../../store/ui'
import { panelQueryKey } from '../source'
import { LogRows } from './LogRows'
import { appendError, isTailing, logLines } from './log'
import type { LogRow } from './shape'

/** The mock's header separator: a neutral-800 pipe between the parts. */
function Bar() {
  return <span className="text-[var(--color-neutral-800)]">│</span>
}

/**
 * The composer: one note, appended to the run's work log as `user`.
 *
 * `POST /api/runs/{id}/log` (08 §Runs) files the entry under the run's
 * current node, or under `user` when the run is not in exactly one — so
 * the composer sends the text and nothing else, and never claims a node
 * on the operator's behalf.
 *
 * It clears **on success only**. A note that was refused is still in the
 * box with the refusal under it, because the operator wrote it and
 * losing it to a 401 or a 422 would be losing the only copy.
 *
 * The panel's own query is invalidated when the write lands. The feed
 * will say the same thing a moment later (`log.appended` is one of the
 * names this panel registered `refresh_on`), but an operator's own note
 * must appear whether or not this tab's stream is up.
 *
 * It is also where `append log` (`l`, and the palette row of the same
 * name) lands: the shell moves the pane cycle here and asks `useUi` for
 * the caret, and this box takes the request the moment it is on screen —
 * which is a render later than the command, because the pane draws once
 * its panel has answered. A request naming another run is not this box's
 * and is left where it is.
 */
function Composer({ runId, source }: { runId: string; source?: string | undefined }) {
  const [text, setText] = useState('')
  const queryClient = useQueryClient()
  const box = useRef<HTMLTextAreaElement | null>(null)
  const askedFor = useUi((state) => state.logComposerFor)
  const clearRequest = useUi((state) => state.clearLogComposer)

  useEffect(() => {
    if (askedFor !== runId) return
    clearRequest()
    box.current?.focus()
  }, [askedFor, runId, clearRequest])

  const mutation = useMutation({
    ...appendLogApiRunsRunIdLogPostMutation(),
    onSuccess: () => {
      setText('')
      if (source !== undefined) {
        void queryClient.invalidateQueries({ queryKey: panelQueryKey(source) })
      }
    },
  })

  const ready = text.trim() !== '' && !mutation.isPending

  const send = () => {
    if (!ready) return
    mutation.mutate({ path: { run_id: runId }, body: { text } })
  }

  return (
    <form
      data-testid="log-composer"
      onSubmit={(event) => {
        event.preventDefault()
        send()
      }}
      className="flex flex-none flex-col gap-[6px] border-t border-[var(--color-neutral-900)] px-[14px] py-[8px]"
    >
      <textarea
        ref={box}
        id="log-composer-text"
        rows={2}
        value={text}
        onChange={(event) => {
          setText(event.target.value)
        }}
        onKeyDown={(event) => {
          // ⌘⏎ / ^⏎ sends, as it does in the new-run overlay (10
          // §Overlays); ⏎ alone is a newline, because a note is prose.
          if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
            event.preventDefault()
            send()
          }
        }}
        aria-label="append a note to the work log"
        placeholder="append a note to the work log"
        className="text-body w-full resize-y rounded-lg border border-border bg-background px-[9px] py-[7px] text-foreground outline-none placeholder:text-[var(--color-neutral-600)] focus-visible:border-[var(--color-accent-600)]"
      />

      <div className="flex flex-wrap items-center gap-[10px]">
        <span className="inline-flex items-center gap-[5px]">
          {/* The key itself is the keyboard map's (10 §Keyboard, T067),
              as the footer's chips are; this is the hint beside the
              field it lands in. */}
          <kbd className="text-hint rounded-lg border border-border bg-[var(--color-neutral-900)] px-[4px] font-mono text-[var(--color-accent-300)]">
            l
          </kbd>
          <span className="text-hint text-muted-foreground">append log</span>
        </span>
        <span className="text-hint text-muted-foreground">⌘⏎ send</span>

        {mutation.isError && (
          <span role="alert" className="text-hint text-status-fail">
            {appendError(mutation.error)}
          </span>
        )}

        <div className="flex-1" />

        <button
          type="submit"
          disabled={!ready}
          data-testid="log-append"
          className="text-hint rounded-lg border border-border px-[8px] py-[2px] tracking-[0.1em] text-[var(--color-accent-300)] enabled:cursor-pointer enabled:hover:border-[var(--color-accent-600)] disabled:text-[var(--color-neutral-600)]"
        >
          {mutation.isPending ? 'appending…' : 'append'}
        </button>
      </div>
    </form>
  )
}

export function Log({
  data,
  runId,
  source,
  node,
  onFilterNode,
}: {
  /** The `log` builtin's answer: the merged rows, oldest first. */
  data: readonly LogRow[]
  /** The run in scope; the pane host resolved it before drawing this. */
  runId: string | undefined
  /** The panel's route, invalidated when a note is appended. */
  source?: string | undefined
  /** `?node=`: show only this node's entries and events (10 §Panes). */
  node?: string | undefined
  /** Write `?node=`; the filter's own control clears it. */
  onFilterNode?: ((node: string | undefined) => void) | undefined
}) {
  const [tailing, setTailing] = useState(true)
  const { data: runs } = useRuns()

  const run = runId === undefined ? undefined : runs?.find((row) => row.id === runId)
  const lines = logLines(data, node)
  // Real data only: until the run's status has arrived, the log is
  // neither claimed to be live nor claimed to be finished (AGENTS.md,
  // "Unknown is omitted"), so the indicator is not drawn at all.
  const status = run?.status
  const live = isTailing(status)

  return (
    <div data-testid="pane-log" className="flex min-h-0 flex-1 flex-col">
      <div className="text-hint flex flex-none flex-wrap items-center gap-x-[10px] gap-y-[6px] border-b border-[var(--color-neutral-900)] px-[14px] py-[6px] tracking-[0.1em] text-muted-foreground">
        <span>EVENT LOG</span>
        <Bar />
        <span data-testid="log-count">{lines.length} lines</span>

        {node !== undefined && (
          <>
            <Bar />
            <button
              type="button"
              data-testid="log-node-filter"
              onClick={() => {
                onFilterNode?.(undefined)
              }}
              disabled={onFilterNode === undefined}
              className="text-hint tracking-[0.1em] text-[var(--color-accent-2-400)] enabled:cursor-pointer enabled:hover:text-[var(--color-accent-200)]"
            >
              node {node} ✕
            </button>
          </>
        )}

        <div className="flex-1" />
        {status !== undefined && (
          <span
            data-testid="log-state"
            className={cn(
              'whitespace-nowrap',
              live
                ? 'animate-ath-pulse text-[var(--color-accent-300)]'
                : 'text-[var(--color-neutral-500)]',
            )}
          >
            {live ? '● tailing' : '○ complete'}
          </span>
        )}
      </div>

      <LogRows
        rows={lines}
        tailing={tailing}
        onTailing={setTailing}
        prose
        empty={
          node === undefined
            ? 'nothing logged yet'
            : `nothing logged under ${node} yet`
        }
      />

      {runId !== undefined && (
        <Composer runId={runId} {...(source === undefined ? {} : { source })} />
      )}
    </div>
  )
}

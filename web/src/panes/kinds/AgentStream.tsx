/**
 * The agent pane: one attempt's transcript, as it arrives
 * (`docs/v1/10-frontend.md` §Panes item 3, and the mock's `isAgent`
 * block in `docs/v1/design/Athanore.dc.html`).
 *
 * `AGENT STREAM · task N · node · streaming/finished · node → model`
 * over the blocks of `./stream.ts`, with a blinking caret while the
 * attempt is live.
 *
 * **It appends; it does not poll and it does not refetch.** The
 * transcript is the one resource on the feed that moves two or three
 * times a second, and `task.stream` is the one event name no glob
 * reaches: `Invalidator.appendStream` fetches `?after=<what the cache
 * holds>` and merges the page into this query's cache entry (10
 * §Realtime and caching). So this pane reads the transcript to its end
 * once, when it opens, and every chunk after that arrives as a small
 * page merged underneath it.
 *
 * **Reading it to the end is more than one request.** `GET
 * /api/tasks/{id}/stream` answers with a page — the oldest 500 chunks
 * after the cursor, `DEFAULT_CHUNK_LIMIT` in
 * `athanore/api/routers/tasks.py` — and reports `last_seq` as the
 * highest sequence *stored*, which is exactly so that a client can tell
 * it has not caught up (08 §Tasks). At the rate a live agent writes,
 * one attempt is routinely several pages, so {@link fetchTranscript}
 * asks again with `after=<the highest sequence it holds>` until it holds
 * `last_seq`. A transcript drawn short with `finished` over it would be
 * a page presented as the whole thing.
 *
 * All of it lands in **one** cache entry: the query keeps the generated
 * key built from a path and no `after`, which is the key
 * `queryKeys.stream(taskId)` names and the prefix the appender merges
 * into. A query asked with an `after` of its own would be a second entry
 * the appender would fill in parallel.
 *
 * **The agent panel declares no `source`.** It is a `custom` panel and a
 * tag (`athanore/plugins/builtin/agent.py`), so its placement comes
 * through the manifest and everything it draws it fetches itself from
 * the wire contract: `GET /api/runs/{id}` for which attempt is running,
 * `GET /api/tasks/{id}/stream` for what that attempt said.
 *
 * **The request panel docks under it.** 10 §Panes item 3: "the request
 * panel docks under the stream when the focused task has open requests
 * … this is where permissions get answered". The dock is the same card
 * the requests pane draws, over the same cache entry
 * (`GET /api/runs/{id}/requests`, `./requests.ts`), narrowed to the
 * attempt on screen: a question raised by an earlier attempt is history
 * and belongs to that pane, not to the turn the operator is watching.
 * It sits outside the transcript's scroller so that scrolling back
 * through what the agent said never takes the answer controls off
 * screen.
 *
 * **Nothing is invented.** The state word is `StreamOut.live`, so a
 * transcript that has not arrived is called neither streaming nor
 * finished, and the body says it is loading rather than that the attempt
 * wrote nothing — "this attempt wrote no transcript" is a fact about a
 * page that came back empty, not about one nobody has answered yet (01
 * §Real data only). The right-hand `node → model` is drawn only once the
 * stats entry has reported a model (05 §Stats entry), because the
 * adapter behind a node is not knowable before an agent has run.
 */
import { useQuery } from '@tanstack/react-query'
import { useVirtualizer } from '@tanstack/react-virtual'
import { useLayoutEffect, useMemo, useRef, useState } from 'react'

import { getStreamApiTasksTaskIdStreamGetOptions } from '../../api/gen/@tanstack/react-query.gen'
import { getStreamApiTasksTaskIdStreamGet } from '../../api/gen/sdk.gen'
import type { StreamChunk, StreamOut, TaskView } from '../../api/gen/types.gen'
import { RequestCard } from '../../components/RequestCard'
import { cn } from '../../lib/utils'
import { ErrorCard } from './cards'
import { openRequestsOf, useRunRequests } from './requests'
import { useRunDetail } from './run'
import {
  focusedTask,
  streamBlocks,
  type StreamBlock,
  type StreamBlockKind,
} from './stream'

/** How far from the bottom still counts as "at the end", in pixels. */
const TAIL_SLACK_PX = 24

/** An estimate for a block nobody has measured yet: a label and a line. */
const BLOCK_ESTIMATE_PX = 52

/** The mock's header separator: a neutral-800 pipe between the parts. */
function Bar() {
  return <span className="text-[var(--color-neutral-800)]">│</span>
}

/** The mock's per-kind label colour (`b.kindStyle`). */
const LABEL_TONES: Record<StreamBlockKind, string> = {
  system: 'text-[var(--color-neutral-600)]',
  assistant: 'text-[var(--color-accent-300)]',
  tool: 'text-[var(--color-accent-2-400)]',
}

/** The mock's per-kind body colour (`b.bodyStyle`). */
const BODY_TONES: Record<StreamBlockKind, string> = {
  system: 'text-[var(--color-neutral-300)]',
  assistant: 'text-[var(--color-neutral-300)]',
  tool: 'text-[var(--color-neutral-400)]',
}

/**
 * One block of the transcript: the mock's card, with the kind, the meta
 * line and a `pre-wrap` body.
 *
 * A `thought` is the one that folds. 10 §Plugin renderers gives it
 * "assistant (dimmed, collapsible)", so it is drawn like an assistant
 * block at half strength and carries a control that hides its body — and
 * it starts **open**, because a transcript that hid the agent's
 * reasoning by default would be one an operator had to go looking
 * through to read what happened (15, D165).
 */
function Block({ block }: { block: StreamBlock }) {
  const [open, setOpen] = useState(true)
  const body = (
    <div
      data-testid="stream-body"
      className={cn(
        'text-row leading-[1.65] whitespace-pre-wrap [overflow-wrap:anywhere]',
        BODY_TONES[block.kind],
      )}
    >
      {block.text}
    </div>
  )

  return (
    <div
      data-testid="stream-block"
      data-kind={block.kind}
      data-chunk={block.chunk}
      className={cn(
        'rounded-lg border border-[var(--color-neutral-900)] px-[11px] py-[9px]',
        block.kind === 'tool' ? 'bg-zebra' : 'bg-card',
        block.thought && 'opacity-60',
      )}
    >
      <div className="mb-[5px] flex items-center gap-[8px]">
        <span
          data-testid="stream-kind"
          className={cn('text-hint tracking-[0.12em]', LABEL_TONES[block.kind])}
        >
          {block.kind}
        </span>
        {block.meta !== '' && (
          <span data-testid="stream-meta" className="text-hint text-muted-foreground">
            {block.meta}
          </span>
        )}
        <div className="flex-1" />
        {block.thought && (
          <button
            type="button"
            data-testid="stream-thought-toggle"
            aria-expanded={open}
            onClick={() => {
              setOpen((was) => !was)
            }}
            className="text-hint cursor-pointer tracking-[0.1em] text-muted-foreground hover:text-[var(--color-accent-200)]"
          >
            {open ? 'hide' : 'show'}
          </button>
        )}
      </div>
      {(!block.thought || open) && body}
    </div>
  )
}

/**
 * The blocks, virtualised, in a scroller that follows the end.
 *
 * The same two hard parts the event log has (`./LogRows.tsx`): a
 * transcript is unbounded in the direction that matters, and a pane
 * opened on a live attempt follows it without dragging back an operator
 * who scrolled up to read something.
 *
 * The caret is deliberately **outside** the virtual list: it belongs to
 * the transcript's end rather than to any block, and a virtualiser only
 * renders what it has indexed.
 */
function Blocks({ blocks, live }: { blocks: readonly StreamBlock[]; live: boolean }) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const [tailing, setTailing] = useState(true)

  // React Compiler is not enabled in this build (`vite.config.ts`), so
  // the hook's un-memoisable return is not the hazard the rule warns of.
  // oxlint-disable-next-line react/incompatible-library
  const virtualizer = useVirtualizer({
    count: blocks.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => BLOCK_ESTIMATE_PX,
    overscan: 6,
    gap: 10,
  })

  // Follow the end while tailing, in the same frame the block was added.
  // The last block's *text* grows too, not just the list, so the length
  // of the transcript is part of what re-runs this.
  const tail = blocks.at(-1)
  useLayoutEffect(() => {
    if (!tailing || blocks.length === 0) return
    virtualizer.scrollToIndex(blocks.length - 1, { align: 'end' })
  }, [tailing, blocks.length, tail?.text.length, virtualizer])

  const items = virtualizer.getVirtualItems()

  return (
    <div
      ref={scrollRef}
      data-testid="stream-scroller"
      onScroll={(event) => {
        const element = event.currentTarget
        const distance = element.scrollHeight - element.scrollTop - element.clientHeight
        setTailing(distance <= TAIL_SLACK_PX)
      }}
      className="min-h-0 flex-1 overflow-x-hidden overflow-y-auto px-[14px] pt-[12px] pb-[24px]"
    >
      {blocks.length === 0 ? (
        <p className="text-row text-muted-foreground" role="status">
          {live
            ? 'the agent has not said anything yet'
            : 'this attempt wrote no transcript'}
        </p>
      ) : (
        <div
          style={{ height: `${String(virtualizer.getTotalSize())}px` }}
          className="relative w-full"
        >
          {items.map((item) => {
            const block = blocks[item.index]
            if (block === undefined) return null
            return (
              <div
                key={block.seq}
                data-index={item.index}
                ref={virtualizer.measureElement}
                style={{ transform: `translateY(${String(item.start)}px)` }}
                className="absolute top-0 left-0 w-full"
              >
                <Block block={block} />
              </div>
            )
          })}
        </div>
      )}

      {live && (
        <div
          data-testid="stream-caret"
          className="mt-[10px] flex items-center gap-[8px] text-muted-foreground"
        >
          <span className="text-row text-[var(--color-accent-400)]">assistant</span>
          <span
            aria-hidden="true"
            className="animate-ath-caret inline-block h-[13px] w-[7px] bg-[var(--color-accent)]"
          />
        </div>
      )}
    </div>
  )
}

/** The highest sequence a set of chunks carries; `0` when it has none. */
function highestSeq(chunks: readonly StreamChunk[]): number {
  return chunks.reduce((highest, chunk) => Math.max(highest, chunk.seq), 0)
}

/**
 * One page of a transcript, straight off the wire.
 *
 * No `limit`: the server's own default is the page size, so the pane
 * asks for history at the size 08 sets rather than at one of its own.
 * `after` is omitted at the start of the transcript, where it means
 * nothing — `after=0` is the endpoint's default (`tasks.py`).
 */
async function streamPage(
  taskId: number,
  after: number,
  signal: AbortSignal,
): Promise<StreamOut> {
  const { data } = await getStreamApiTasksTaskIdStreamGet({
    path: { task_id: taskId },
    ...(after === 0 ? {} : { query: { after } }),
    signal,
    throwOnError: true,
  })
  return data
}

/**
 * The transcript, read to its end: a first page, then a page after every
 * sequence held, until what is held reaches the server's `last_seq`.
 *
 * `last_seq` is the highest sequence **stored**, not the highest in the
 * page (08 §Tasks), so the two being equal is the endpoint's own way of
 * saying there is no more — and the only way a client can know, since a
 * full page and a final page look alike.
 *
 * A page that carries nothing past what is already held ends the loop.
 * The server has said `last_seq` is higher and then has not produced it,
 * which is a transcript deleted between the two requests (07 §Retention)
 * or a server that does not answer as 08 says — either way a reason to
 * stop, not to ask forever. What was read is drawn, and `last_seq` still
 * says where the transcript ends, so a later append fills the gap.
 */
async function fetchTranscript(
  taskId: number,
  signal: AbortSignal,
): Promise<StreamOut> {
  let page = await streamPage(taskId, 0, signal)
  let chunks = page.chunks
  let held = highestSeq(chunks)

  while (held < page.last_seq) {
    page = await streamPage(taskId, held, signal)
    const reached = highestSeq(page.chunks)
    if (reached <= held) break
    chunks = [...chunks, ...page.chunks]
    held = reached
  }

  return { chunks, last_seq: page.last_seq, live: page.live }
}

/**
 * `GET /api/tasks/{id}/stream`: the whole transcript, read once.
 *
 * The key is the generated one, built from a path and no `after`, so it
 * is exactly the prefix the invalidation table appends into — see the
 * module docstring. The function under it is this module's, because the
 * generated one fetches a single page and the pane wants the transcript.
 */
function useStream(taskId: number | undefined) {
  const { queryKey } = getStreamApiTasksTaskIdStreamGetOptions({
    path: { task_id: taskId ?? 0 },
  })
  return useQuery({
    queryKey,
    queryFn: ({ signal }) => fetchTranscript(taskId ?? 0, signal),
    enabled: taskId !== undefined,
  })
}

/** `node → claude-opus-5`, or nothing when no agent has reported one. */
function adapterLine(task: TaskView): string | undefined {
  const model = (task.stats ?? {})['model']
  return typeof model === 'string' && model !== ''
    ? `${task.node} → ${model}`
    : undefined
}

export function AgentStream({
  runId,
  taskId,
}: {
  /** The run in scope, from `?run=`. */
  runId: string | undefined
  /** The task drawer's override, from `?task=` (10 §Layout). */
  taskId?: number | undefined
}) {
  const detail = useRunDetail(runId)
  const task = focusedTask(detail?.tasks, taskId)
  const { data: stream, isError, error } = useStream(task?.id)
  const { data: requests } = useRunRequests(runId)
  const open = openRequestsOf(requests, task?.id)

  const blocks = useMemo(() => streamBlocks(stream?.chunks ?? []), [stream])
  const live = stream?.live ?? false
  const adapter = task === undefined ? undefined : adapterLine(task)

  return (
    <div data-testid="pane-agent" className="flex min-h-0 flex-1 flex-col">
      <div className="text-hint flex flex-none flex-wrap items-center gap-x-[10px] gap-y-[6px] border-b border-[var(--color-neutral-800)] px-[14px] py-[6px] tracking-[0.1em] text-muted-foreground">
        <span className="whitespace-nowrap">AGENT STREAM</span>
        {task !== undefined && (
          <>
            <Bar />
            <span
              data-testid="stream-task"
              className="whitespace-nowrap text-[var(--color-neutral-300)]"
            >
              task {task.id} · {task.node}
              {stream === undefined ? '' : live ? ' · streaming' : ' · finished'}
            </span>
          </>
        )}
        <div className="flex-1" />
        {adapter !== undefined && (
          <span data-testid="stream-adapter" className="whitespace-nowrap">
            {adapter}
          </span>
        )}
      </div>

      {runId === undefined ? (
        <p className="text-row p-[12px_14px] text-muted-foreground" role="status">
          select a run to follow an agent
        </p>
      ) : task === undefined ? (
        <p className="text-row p-[12px_14px] text-muted-foreground" role="status">
          {detail === undefined
            ? 'loading the run…'
            : 'no agent has run in this run yet'}
        </p>
      ) : isError ? (
        // The transcript is the pane's own request, so its failure is
        // named here rather than left to look like an attempt that said
        // nothing (09 §Panel kinds' promise, in `./cards.tsx`).
        <div className="p-[12px_14px]">
          <ErrorCard
            message={error instanceof Error ? error.message : 'the request failed'}
            source={`/api/tasks/${String(task.id)}/stream`}
          />
        </div>
      ) : stream === undefined ? (
        <p className="text-row p-[12px_14px] text-muted-foreground" role="status">
          loading the transcript…
        </p>
      ) : (
        <Blocks blocks={blocks} live={live} />
      )}

      {open.length > 0 && (
        <div
          data-testid="stream-request-dock"
          className="bg-chrome flex max-h-[45%] flex-none flex-col gap-[8px] overflow-x-hidden overflow-y-auto border-t border-[var(--color-neutral-800)] px-[14px] py-[10px]"
        >
          <p className="text-hint tracking-[0.1em] text-status-gate">
            <span aria-hidden="true">⚠ </span>
            {open.length === 1
              ? 'WAITING ON YOU'
              : `WAITING ON YOU · ${String(open.length)} REQUESTS`}
          </p>
          {open.map((request) => (
            <RequestCard key={request.id} request={request} />
          ))}
        </div>
      )}
    </div>
  )
}

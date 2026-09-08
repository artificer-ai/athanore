/**
 * How the agent pane reads a transcript: which attempt it is about, and
 * what one chunk becomes (`docs/v1/10-frontend.md` §Panes item 3 and
 * §Plugin renderers, over `StreamChunk` of 03 §StreamChunk).
 *
 * Separate from `./AgentStream.tsx` for the reason `./log.ts` is
 * separate from `./Log.tsx`: a component module that also exports
 * functions is one React Fast Refresh cannot update in place
 * (`.oxlintrc.json`, `react/only-export-components`).
 *
 * Two decisions live here and nowhere else.
 *
 * **The mapping is 10's, exactly**: `notice → system`, `text →
 * assistant`, `thought → assistant` (dimmed and collapsible),
 * `tool_call` / `tool_result → tool`. A kind this build has no rule for
 * — a transcript written by a later Athanore — is drawn as `system`
 * under its own name rather than dropped, because the text is still the
 * agent's (01 §Real data only).
 *
 * **Only the streamed kinds coalesce.** `text` and `thought` arrive as
 * content-block fragments, two or three a second, and one bordered card
 * per fragment is not a paragraph; consecutive chunks of the same kind
 * are therefore one block. `notice`, `tool_call` and `tool_result` are
 * whole utterances the façade writes one at a time — a sentence, a tool
 * call's title, a tool's output (`athanore/agents/acp.py`) — so each is
 * its own block and two tool calls in a row stay two rows (15, D165).
 */
import type { ChunkKind, StreamChunk, TaskView } from '../../api/gen/types.gen'

/** The three block classes the mock draws (10 §Panes item 3). */
export type StreamBlockKind = 'system' | 'assistant' | 'tool'

/** 10 §Plugin renderers' mapping, and the whole of it. */
const BLOCK_KINDS: Record<ChunkKind, StreamBlockKind> = {
  notice: 'system',
  text: 'assistant',
  thought: 'assistant',
  tool_call: 'tool',
  tool_result: 'tool',
}

/**
 * What the block's meta line says, for the kinds whose block class alone
 * would lose which chunk it came from.
 *
 * `notice` is the only `system` and `text` the only plain `assistant`,
 * so their labels would repeat what the block already says.
 */
const CHUNK_LABELS: Partial<Record<ChunkKind, string>> = {
  thought: 'thought',
  tool_call: 'tool call',
  tool_result: 'tool result',
}

/** The kinds that arrive in fragments and are read as one paragraph. */
const STREAMED: ReadonlySet<string> = new Set<ChunkKind>(['text', 'thought'])

/** The attempt statuses that mean the transcript may still grow (08). */
const IN_FLIGHT: ReadonlySet<string> = new Set(['in_progress', 'waiting'])

/** One block of the transcript: a run of chunks drawn as one card. */
export type StreamBlock = {
  /** The first chunk's sequence: the block's key, stable across appends. */
  seq: number
  /** Which of the mock's three blocks this is. */
  kind: StreamBlockKind
  /** The chunk kind it came from, as the server named it. */
  chunk: string
  /** The meta line, or `''` when the block's own label says it all. */
  meta: string
  /** Dimmed and collapsible: a `thought` (10 §Plugin renderers). */
  thought: boolean
  /** The text, in sequence order. */
  text: string
}

/** The block class `kind` is drawn as; an unknown kind degrades. */
export function blockKind(kind: string): StreamBlockKind {
  return BLOCK_KINDS[kind as ChunkKind] ?? 'system'
}

/** The meta line for `kind`, or `''` where the block label repeats it. */
export function chunkLabel(kind: string): string {
  if (Object.hasOwn(BLOCK_KINDS, kind)) return CHUNK_LABELS[kind as ChunkKind] ?? ''
  // A kind this build has no rule for is named outright: the block says
  // `system` because that is the neutral frame, and the meta says what
  // the server actually called it.
  return kind
}

/**
 * The transcript as blocks, oldest first.
 *
 * Sorted by `seq` rather than trusted in arrival order: the page is in
 * sequence order (08 §Tasks) and the appender merges in sequence order
 * (`src/realtime/invalidate.ts`), so this only ever confirms both — and
 * a block list is what the virtualiser indexes by, so it may not depend
 * on either of them staying true.
 */
export function streamBlocks(chunks: readonly StreamChunk[]): StreamBlock[] {
  const ordered = [...chunks].sort((a, b) => a.seq - b.seq)
  const blocks: StreamBlock[] = []

  for (const chunk of ordered) {
    const last = blocks.at(-1)
    if (last !== undefined && last.chunk === chunk.kind && STREAMED.has(chunk.kind)) {
      last.text += chunk.text
      continue
    }
    blocks.push({
      seq: chunk.seq,
      kind: blockKind(chunk.kind),
      chunk: chunk.kind,
      meta: chunkLabel(chunk.kind),
      thought: chunk.kind === 'thought',
      text: chunk.text,
    })
  }

  return blocks
}

/**
 * The attempt the pane is about (10 §Panes item 3, T063c).
 *
 * The task drawer's `?task=` wins when it names an attempt of this run —
 * an operator who opened an attempt is reading that one — and a `?task=`
 * left over from another run is ignored rather than followed into a
 * transcript this pane is not scoped to.
 *
 * Otherwise it is the run's most recent in-flight attempt: `in_progress`
 * or `waiting`, the pair 08 calls `live`, because a waiting attempt is
 * parked on a request and goes on writing once it is answered. A run
 * with nothing in flight falls back to its most recent attempt that an
 * agent measured — the same "most recent agent attempt" the overview's
 * SESSION field means (10 §Panes item 1) — so a finished run still shows
 * the transcript it ended on rather than nothing at all (15, D165).
 *
 * `RunDetail.tasks` is oldest first (08 §Runs), so the last match wins.
 */
export function focusedTask(
  tasks: readonly TaskView[] | undefined,
  override?: number | undefined,
): TaskView | undefined {
  const rows = tasks ?? []
  if (override !== undefined) {
    const chosen = rows.find((task) => task.id === override)
    if (chosen !== undefined) return chosen
  }

  let inFlight: TaskView | undefined
  let measured: TaskView | undefined
  for (const task of rows) {
    if (IN_FLIGHT.has(task.status)) inFlight = task
    if (task.stats != null) measured = task
  }
  return inFlight ?? measured
}

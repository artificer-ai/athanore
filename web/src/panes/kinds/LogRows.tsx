/**
 * The rows of a log, in a scroller that follows the end: the mock's
 * `time · source · message` grid (`docs/v1/10-frontend.md` §Panes).
 *
 * Two panes draw it. `./LogPane.tsx` is the `log` *kind* any plugin may
 * declare (09 §Panel kinds), and `./Log.tsx` is the builtin event log,
 * which adds the header, the composer and the `?node=` filter around
 * exactly these rows. The list itself is one implementation because the
 * two hard parts of it are the same for both:
 *
 * - **it is virtualised.** A run's merged work log and event history is
 *   unbounded in the only direction that matters — a long run keeps
 *   adding to it — so `@tanstack/react-virtual` renders the rows in view
 *   and measures each one, because a wrapped multi-line deliverable is
 *   not the same height as an edge.
 * - **it tails.** A pane opened on a running run follows the end, and an
 *   operator who scrolls up to read something is not dragged back down
 *   by the next event; coming back to the bottom follows again.
 *
 * Following is *controlled*: the state lives in the pane above, because
 * that is what the pane's header says out loud — `● tailing / ○ paused`
 * on a plugin's log, which is a toggle, and `● tailing / ○ complete` on
 * the builtin's, which is the run's own status (10 §Panes).
 *
 * `source` is 10's middle column and is not in 09's shape — the builtin
 * log route adds it (`athanore/plugins/builtin/log.py`) and a plugin's
 * rows may not have it, so the column is drawn only where it is there.
 */
import { useVirtualizer } from '@tanstack/react-virtual'
import { useEffect, useLayoutEffect, useRef } from 'react'

import { cn } from '../../lib/utils'
import { MarkdownPane } from './MarkdownPane'
import { rowTime } from './format'
import { isProse, logTone } from './log'
import type { LogRow } from './shape'

/** How far from the bottom still counts as "at the end", in pixels. */
export const TAIL_SLACK_PX = 24

/** An estimate for a row nobody has measured yet: one line plus padding. */
const ROW_ESTIMATE_PX = 18

export function LogRows({
  rows,
  tailing,
  onTailing,
  prose = false,
  empty = 'nothing logged yet',
}: {
  /** The rows to draw, in the order they are drawn (`./log.ts`). */
  rows: readonly LogRow[]
  /** Whether the scroller follows the end. */
  tailing: boolean
  /** Scrolling away from the end, and back to it, is reported here. */
  onTailing: (tailing: boolean) => void
  /**
   * Render what an agent or a person wrote as markdown (10 §Panes).
   *
   * Off for a plugin's `log` panel, whose rows are lines of a log and
   * carry no author to decide it by.
   */
  prose?: boolean
  /** What to say instead of an empty scroller. */
  empty?: string
}) {
  const scrollRef = useRef<HTMLDivElement>(null)

  // React Compiler is not enabled in this build (`vite.config.ts`), so
  // the hook's un-memoisable return is not the hazard the rule warns of;
  // the virtualiser is what 17 §T062a names for this pane.
  // oxlint-disable-next-line react/incompatible-library
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_ESTIMATE_PX,
    overscan: 12,
  })

  // Follow the end while tailing. A layout effect rather than an effect:
  // the jump happens in the same frame the row was added, so the list
  // never paints one frame short of the bottom.
  useLayoutEffect(() => {
    if (!tailing || rows.length === 0) return
    virtualizer.scrollToIndex(rows.length - 1, { align: 'end' })
  }, [tailing, rows.length, virtualizer])

  // Reading something means not being dragged back down by the next
  // event; coming back to the bottom means following again.
  useEffect(() => {
    const element = scrollRef.current
    if (element === null) return
    const onScroll = () => {
      const distance = element.scrollHeight - element.scrollTop - element.clientHeight
      onTailing(distance <= TAIL_SLACK_PX)
    }
    element.addEventListener('scroll', onScroll, { passive: true })
    return () => {
      element.removeEventListener('scroll', onScroll)
    }
  }, [onTailing])

  const withSource = rows.some((row) => row.source !== undefined)
  const items = virtualizer.getVirtualItems()

  return (
    <div
      ref={scrollRef}
      data-testid="log-scroller"
      className="min-h-0 flex-1 overflow-x-hidden overflow-y-auto px-[14px] pt-[8px] pb-[20px]"
    >
      {rows.length === 0 ? (
        <p className="text-row text-muted-foreground" role="status">
          {empty}
        </p>
      ) : (
        <div
          style={{ height: `${String(virtualizer.getTotalSize())}px` }}
          className="relative w-full"
        >
          {items.map((item) => {
            const row = rows[item.index]
            if (row === undefined) return null
            const markdown = prose && isProse(row)
            return (
              <div
                key={item.key}
                data-index={item.index}
                ref={virtualizer.measureElement}
                style={{ transform: `translateY(${String(item.start)}px)` }}
                className={cn(
                  'absolute top-0 left-0 grid w-full gap-[8px] py-px',
                  withSource
                    ? 'grid-cols-[minmax(0,58px)_minmax(0,130px)_minmax(120px,1fr)]'
                    : 'grid-cols-[minmax(0,58px)_minmax(120px,1fr)]',
                )}
              >
                <span className="text-meta text-muted-foreground">
                  {rowTime(row.ts)}
                </span>
                {withSource && (
                  <span className="text-meta truncate text-[var(--color-accent-2-400)]">
                    {row.source ?? ''}
                  </span>
                )}
                <div
                  data-testid="log-message"
                  data-markdown={markdown}
                  className={cn(
                    'text-row [overflow-wrap:anywhere]',
                    !markdown && 'whitespace-pre-wrap',
                    logTone(row.level),
                  )}
                >
                  {markdown ? <MarkdownPane text={row.text} /> : row.text}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

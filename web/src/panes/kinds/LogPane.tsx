/**
 * `log`: `[{ts, text, level?}]` as an autoscrolling stream (09 §Panel
 * kinds), drawn as the mock's `time · source · message` rows (10
 * §Panes).
 *
 * Two things make it a log rather than a list:
 *
 * - **it is virtualised.** A run's merged work log and event history is
 *   unbounded in the only direction that matters — a long run keeps
 *   adding to it — so `@tanstack/react-virtual` renders the rows in
 *   view and measures each one, because a wrapped multi-line
 *   deliverable is not the same height as an edge.
 * - **it tails.** A pane opened on a running run follows the end, and an
 *   operator who scrolls up to read something is not dragged back down
 *   by the next event. Scrolling away from the bottom therefore turns
 *   tailing off, and the toggle — which reads `● tailing` / `○ paused`,
 *   the mock's own glyphs — turns it back on and jumps to the end.
 *
 * The strip carrying the count and the toggle sits above the scroller
 * rather than inside it: it stays put while the rows move, and the
 * virtualiser never has to allow for a sticky row's height.
 *
 * `source` is 10's middle column and is not in 09's shape — the builtin
 * log route adds it (`athanore/plugins/builtin/log.py`) and a plugin's
 * rows may not have it, so the column is drawn only where it is there.
 * `level` is a *tone*, not a severity: 10 §Panes names exactly three.
 */
import { useVirtualizer } from '@tanstack/react-virtual'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'

import { cn } from '../../lib/utils'
import { rowTime } from './format'
import type { LogRow } from './shape'

/** 10 §Panes' three tones, as the classes that draw them. */
const TONES: Record<string, string> = {
  accent: 'text-[var(--color-accent-300)]',
  dim: 'text-muted-foreground',
  default: 'text-[var(--color-neutral-300)]',
}

/** How far from the bottom still counts as "at the end", in pixels. */
const TAIL_SLACK_PX = 24

/** An estimate for a row nobody has measured yet: one line plus padding. */
const ROW_ESTIMATE_PX = 18

export function LogPane({ rows }: { rows: readonly LogRow[] }) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const [tailing, setTailing] = useState(true)
  const withSource = rows.some((row) => row.source !== undefined)

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
      const distance =
        element.scrollHeight - element.scrollTop - element.clientHeight
      setTailing(distance <= TAIL_SLACK_PX)
    }
    element.addEventListener('scroll', onScroll, { passive: true })
    return () => {
      element.removeEventListener('scroll', onScroll)
    }
  }, [])

  const items = virtualizer.getVirtualItems()

  return (
    <div data-testid="pane-log" className="flex min-h-0 flex-1 flex-col">
      <div className="text-hint flex flex-none items-center gap-[10px] border-b border-[var(--color-neutral-900)] px-[14px] py-[6px] tracking-[0.1em] text-muted-foreground">
        <span data-testid="log-count">{rows.length} lines</span>
        <div className="flex-1" />
        <button
          type="button"
          aria-pressed={tailing}
          onClick={() => {
            setTailing((on) => !on)
          }}
          data-testid="log-tailing"
          className={cn(
            'text-hint cursor-pointer tracking-[0.1em]',
            tailing
              ? 'text-[var(--color-accent-300)]'
              : 'text-[var(--color-neutral-500)] hover:text-[var(--color-accent-200)]',
          )}
        >
          {tailing ? '● tailing' : '○ paused'}
        </button>
      </div>

      <div
        ref={scrollRef}
        data-testid="log-scroller"
        className="min-h-0 flex-1 overflow-x-hidden overflow-y-auto px-[14px] pt-[8px] pb-[20px]"
      >
        {rows.length === 0 ? (
          <p className="text-row text-muted-foreground" role="status">
            nothing logged yet
          </p>
        ) : (
          <div
            style={{ height: `${String(virtualizer.getTotalSize())}px` }}
            className="relative w-full"
          >
            {items.map((item) => {
              const row = rows[item.index]
              if (row === undefined) return null
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
                  <span
                    className={cn(
                      'text-row [overflow-wrap:anywhere] whitespace-pre-wrap',
                      TONES[row.level ?? 'default'] ?? TONES['default'],
                    )}
                  >
                    {row.text}
                  </span>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}

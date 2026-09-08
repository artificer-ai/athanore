/**
 * `log`: `[{ts, text, level?}]` as an autoscrolling stream (09 §Panel
 * kinds), drawn as the mock's `time · source · message` rows (10
 * §Panes).
 *
 * This is the kind *any* plugin may declare. The core's own event log is
 * `./Log.tsx`, which draws the same rows with the header, the composer
 * and the `?node=` filter 10 §Panes item 2 gives that pane; the list
 * both of them scroll is `./LogRows.tsx`.
 *
 * The strip carrying the count and the toggle sits above the scroller
 * rather than inside it: it stays put while the rows move, and the
 * virtualiser never has to allow for a sticky row's height. The toggle
 * reads `● tailing` / `○ paused` — the mock's own glyphs — and turns
 * following back on, which is what an operator who scrolled up to read
 * something reaches for.
 *
 * A plugin's rows arrive in whatever order its route sent them, so they
 * are ordered here rather than trusted ({@link logLines}); the tones are
 * 10's three, and `level` is one of them rather than a severity.
 */
import { useState } from 'react'

import { cn } from '../../lib/utils'
import { LogRows } from './LogRows'
import { logLines } from './log'
import type { LogRow } from './shape'

export function LogPane({ rows }: { rows: readonly LogRow[] }) {
  const [tailing, setTailing] = useState(true)
  const lines = logLines(rows)

  return (
    <div data-testid="pane-log" className="flex min-h-0 flex-1 flex-col">
      <div className="text-hint flex flex-none items-center gap-[10px] border-b border-[var(--color-neutral-900)] px-[14px] py-[6px] tracking-[0.1em] text-muted-foreground">
        <span data-testid="log-count">{lines.length} lines</span>
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

      <LogRows rows={lines} tailing={tailing} onTailing={setTailing} />
    </div>
  )
}

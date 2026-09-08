/**
 * The strip under the header that says nothing is answering, and when
 * the next attempt is due (`docs/v1/10-frontend.md` §Realtime and
 * caching).
 *
 * It is a strip rather than an overlay on purpose: "the last data stays
 * visible" is the mock's server-down behaviour, so what a run looked
 * like a moment ago is still readable while the connection is out. The
 * header's counts grey out beside it (`Header.tsx`), which is the other
 * half of the same signal — greyed numbers are numbers nobody is
 * standing behind any more.
 *
 * A dropped connection that comes straight back says nothing here: the
 * feed only reports `down` once a retry has failed too (`sse.ts`).
 */
import { useEffect, useState } from 'react'

import { appEventFeed } from '../realtime/sse'
import { useUi } from '../store/ui'

/** How often the countdown redraws. */
export const TICK_MS = 250

/**
 * Seconds until `retryAt`, or `null` when an attempt is already in
 * flight and there is nothing to count towards.
 *
 * The clock is read on the tick and nowhere else: `Date.now()` during a
 * render is a value that changes without a state change, and React is
 * entitled to render whenever it likes. The tick therefore carries the
 * attempt it counted, and a count left over from the last attempt is
 * discarded rather than shown — which is also why the first quarter of
 * a second reads "reconnecting…" rather than a number.
 */
function useCountdown(retryAt: number | null): number | null {
  const [ticked, setTicked] = useState<{ at: number; seconds: number } | null>(null)

  useEffect(() => {
    if (retryAt === null) return
    const timer = setInterval(() => {
      setTicked({
        at: retryAt,
        seconds: Math.max(0, Math.ceil((retryAt - Date.now()) / 1000)),
      })
    }, TICK_MS)
    return () => clearInterval(timer)
  }, [retryAt])

  return ticked?.at === retryAt ? ticked.seconds : null
}

export function ServerDownBanner() {
  const status = useUi((state) => state.feed.status)
  const retryAt = useUi((state) => state.feed.retryAt)
  const seconds = useCountdown(retryAt)

  if (status !== 'down') return null

  return (
    <div
      role="status"
      data-testid="server-down-banner"
      className="text-meta flex flex-none flex-wrap items-center gap-x-[10px] gap-y-[4px] border-b border-border bg-chrome px-[14px] py-[6px] text-muted-foreground"
    >
      <span className="text-status-fail font-medium tracking-[0.12em] uppercase">
        <span aria-hidden>▲ </span>no server
      </span>
      <span>
        Nothing is answering <Code>GET /api/events</Code> — what is on screen is
        the last this tab was told.
      </span>
      <span data-testid="server-down-countdown">
        {seconds === null ? 'reconnecting…' : `retrying in ${seconds}s`}
      </span>
      <button
        type="button"
        onClick={() => appEventFeed()?.reconnectNow()}
        className="rounded-lg border border-border px-[8px] py-px text-[var(--color-accent-200)] hover:border-[var(--color-accent-600)] hover:bg-[var(--color-accent-900)]"
      >
        try now
      </button>
    </div>
  )
}

function Code({ children }: { children: string }) {
  return (
    <code className="rounded-sm bg-[var(--color-neutral-900)] px-[4px] py-px text-[var(--color-accent-200)]">
      {children}
    </code>
  )
}

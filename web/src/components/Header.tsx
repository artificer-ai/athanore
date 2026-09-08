/**
 * The header strip: brand mark, version, and the two counts
 * (`docs/v1/10-frontend.md` §Layout).
 *
 * The counts are placeholders until T059 fetches `GET /api/runs`. They
 * read `—` rather than `0`, because 02 §Real data only says an unknown
 * number is omitted, never zero-filled — and the active dot only pulses
 * while something is in progress, which nothing yet is.
 *
 * The one "fading rule" of 10 §Borders sits under the strip: transparent
 * to accent 75 % to transparent, inset 48 px at each end.
 *
 * When the event feed is down the counts grey out and the dot stops
 * pulsing (10 §Realtime and caching): the numbers are still the last
 * ones the server gave, and greying them is how the strip says nobody is
 * standing behind them any more. `ServerDownBanner` says why, underneath.
 */
import { useUi } from '../store/ui'

/** Injected by `vite.config.ts` from `pyproject.toml`'s `[project] version`. */
const VERSION = __APP_VERSION__

export function Header() {
  const down = useUi((state) => state.feed.status === 'down')

  return (
    <header className="bg-chrome relative flex flex-none flex-wrap items-center gap-x-[14px] gap-y-2 border-b border-border px-[14px] py-[8px]">
      <div className="flex items-baseline gap-[8px]">
        <h1 className="text-body font-bold tracking-[0.12em] text-[var(--color-accent-300)]">
          <span aria-hidden>▚ </span>ATHANORE
        </h1>
        <span className="text-meta text-muted-foreground">v{VERSION}</span>
      </div>

      <div
        data-testid="header-counts"
        data-down={down}
        className="text-meta group flex items-center gap-[10px] whitespace-nowrap text-muted-foreground data-[down=true]:text-[var(--color-neutral-700)]"
      >
        <span data-testid="run-count">— runs</span>
        <span aria-hidden className="text-[var(--color-neutral-800)]">
          │
        </span>
        <span className="inline-flex items-center gap-[5px]" data-testid="active-count">
          <span
            aria-hidden
            data-active="false"
            className="h-[6px] w-[6px] flex-none rounded-full bg-[var(--color-neutral-700)] data-[active=true]:bg-[var(--color-accent)] data-[active=true]:animate-ath-pulse group-data-[down=true]:animate-none group-data-[down=true]:bg-[var(--color-neutral-800)]"
          />
          — active
        </span>
      </div>

      <span
        aria-hidden
        className="pointer-events-none absolute inset-x-[48px] bottom-0 h-px"
        style={{
          background:
            'linear-gradient(90deg, transparent, color-mix(in srgb, var(--color-accent) 75%, transparent), transparent)',
        }}
      />
    </header>
  )
}

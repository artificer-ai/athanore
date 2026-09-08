/**
 * The header strip: brand mark, version, the two counts, and the run
 * list's filters (`docs/v1/10-frontend.md` §Layout).
 *
 * The counts are `GET /api/runs`, which is also what the list draws, so
 * the number in the strip and the number of rows under it can never
 * disagree. Before the server has answered they read `—` rather than
 * `0`: 02 §Real data only says an unknown number is omitted, never
 * zero-filled. The active dot pulses only while `k > 0` — "only while
 * something is in progress" (10 §Attention) — and is neutral otherwise.
 *
 * The one "fading rule" of 10 §Borders sits under the strip: transparent
 * to accent 75 % to transparent, inset 48 px at each end.
 *
 * When the event feed is down the counts grey out and the dot stops
 * pulsing (10 §Realtime and caching): the numbers are still the last
 * ones the server gave, and greying them is how the strip says nobody is
 * standing behind them any more. `ServerDownBanner` says why, underneath.
 *
 * `＋ new run` is the mock's one primary control and writes
 * `?overlay=new` through the shell (T066b); `workflows` beside it is the
 * same gesture for `?overlay=library` (T066c), in the mock's neutral
 * outline rather than the accent one, because there is one primary
 * button in the app (10 §Components).
 */
import { RunFilters } from './RunList'
import type { RunListModel } from './RunList'
import { useUi } from '../store/ui'

/** Injected by `vite.config.ts` from `pyproject.toml`'s `[project] version`. */
const VERSION = __APP_VERSION__

/** A count the server has not given yet (02 §Real data only). */
const UNKNOWN = '—'

export function Header({
  runs,
  onNewRun,
  onOpenLibrary,
}: {
  runs: RunListModel
  /** Open the New Run overlay: `?overlay=new` (10 §Overlays). */
  onNewRun: () => void
  /** Open the workflow library: `?overlay=library` (10 §Overlays). */
  onOpenLibrary: () => void
}) {
  const down = useUi((state) => state.feed.status === 'down')
  const active = runs.active ?? 0

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
        <span data-testid="run-count">{runs.total ?? UNKNOWN} runs</span>
        <span aria-hidden className="text-[var(--color-neutral-800)]">
          │
        </span>
        <span className="inline-flex items-center gap-[5px]" data-testid="active-count">
          <span
            aria-hidden
            data-active={active > 0}
            className="h-[6px] w-[6px] flex-none rounded-full bg-[var(--color-neutral-700)] data-[active=true]:bg-[var(--color-accent)] data-[active=true]:animate-ath-pulse group-data-[down=true]:animate-none group-data-[down=true]:bg-[var(--color-neutral-800)]"
          />
          {runs.active ?? UNKNOWN} active
        </span>
      </div>

      <div className="flex-1" />

      <RunFilters workflows={runs.workflows} />

      {/* The one primary button in the app: outlined with the accent as
          border and text, never as a fill (10 §Components, §Tokens). */}
      <button
        type="button"
        onClick={onNewRun}
        className="text-meta cursor-pointer rounded-lg border border-[var(--color-accent-700)] px-[10px] py-[4px] text-[var(--color-accent-200)] hover:border-[var(--color-accent)] hover:bg-[var(--color-accent-900)]"
      >
        <span aria-hidden>＋ </span>new run
      </button>

      {/* The mock's neutral outline beside it: `w`, the palette's row and
          this button are three ways of writing the same parameter. */}
      <button
        type="button"
        onClick={onOpenLibrary}
        className="text-meta cursor-pointer rounded-lg border border-border px-[10px] py-[4px] text-[var(--color-neutral-400)] hover:border-[var(--color-accent-600)] hover:text-[var(--color-accent-200)]"
      >
        workflows
      </button>

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

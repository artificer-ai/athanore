/**
 * The header strip: brand mark, version, the two counts, and the run
 * list's filters.
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
 *
 * Below the breakpoint the strip wraps (21 §Narrow layout): the brand,
 * the version, the counts and the three controls above, and the chips
 * and the `/` filter below them as one horizontally scrollable row.
 * Nothing is dropped and nothing shrinks — the strip scrolls *itself*,
 * which is the one horizontal scroll 21 allows, and the page never
 * does. The wrapper around `RunFilters` is `display: contents` at `md`
 * and above, so the filter controls stay direct children of this flex
 * box there and the desktop strip is the same box it was.
 *
 * {@link FontSizeMenu} sits beside them: the header is the one chrome
 * that is always on screen, which is why the type-size chooser lives
 * here rather than behind a settings overlay the SPA does not have
 * (D196). The palette's four `font size: …` rows are the same choice
 * from the keyboard.
 */
import { TextAaIcon } from '@phosphor-icons/react'
import { Popover, RadioGroup } from 'radix-ui'

import { RunFilters } from './RunList'
import type { RunListModel } from './RunList'
import { FONT_SIZES, usePrefs, type FontSize } from '../store/prefs'
import { useUi } from '../store/ui'

/** Injected by `vite.config.ts` from `pyproject.toml`'s `[project] version`. */
const VERSION = __APP_VERSION__

/** A count the server has not given yet (02 §Real data only). */
const UNKNOWN = '—'

/**
 * The touch target of WCAG 2.5.8 on the narrow chrome's controls.
 *
 * A minimum and not a size: at 12 px the two header buttons already
 * clear it, and this is what keeps them clearing it at `small`.
 */
const TOUCH = 'max-md:min-h-[24px] max-md:min-w-[24px]'

/**
 * The type-size chooser: an icon-only button opening a popover with the
 * four steps of the ramp as a radio group (21 §Type scale, D196).
 *
 * It writes `usePrefs.fontSize` and nothing else. What that step *means*
 * is the generated theme's — `data-font-size` on `<html>`, written by
 * `syncFontSize()` — so no size in the app is decided here, and the
 * ramp cannot go half-scaled.
 *
 * The trigger is 24×24 px and each row is at least 24 px tall (WCAG
 * 2.5.8), which is also what makes the control usable by touch. The icon
 * is sized in pixels rather than in `em`: what scales is type, not
 * chrome (D195).
 */
export function FontSizeMenu() {
  const fontSize = usePrefs((state) => state.fontSize)
  const setFontSize = usePrefs((state) => state.setFontSize)

  return (
    <Popover.Root>
      <Popover.Trigger
        aria-label="text size"
        title="text size"
        className="flex h-[24px] w-[24px] cursor-pointer items-center justify-center rounded-lg border border-border text-[var(--color-neutral-400)] hover:border-[var(--color-accent-600)] hover:text-[var(--color-accent-200)]"
      >
        <TextAaIcon size={14} weight="regular" aria-hidden />
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          align="end"
          sideOffset={6}
          data-testid="font-size"
          className="z-50 rounded-lg border border-border bg-card p-[4px] shadow-md"
        >
          <RadioGroup.Root
            aria-label="text size"
            value={fontSize}
            onValueChange={(value) => setFontSize(value as FontSize)}
            className="flex flex-col"
          >
            {FONT_SIZES.map((step) => (
              <RadioGroup.Item
                key={step}
                value={step}
                data-font-size={step}
                className="text-meta flex min-h-[24px] cursor-pointer items-center gap-[8px] rounded-lg px-[8px] py-[4px] text-[var(--color-neutral-400)] hover:bg-zebra data-[state=checked]:text-[var(--color-accent-200)]"
              >
                {/* The dot marks the current step for a sighted reader;
                    `aria-checked` is Radix's and says it to every other
                    one, so the glyph is hidden from the tree. */}
                <span
                  aria-hidden
                  className="flex w-[6px] flex-none justify-center text-[var(--color-accent)]"
                >
                  <RadioGroup.Indicator>●</RadioGroup.Indicator>
                </span>
                {step}
              </RadioGroup.Item>
            ))}
          </RadioGroup.Root>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  )
}

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

      {/* `contents` above the breakpoint: the chips and the `/` box are
          the header's own flex children there, and this element draws
          nothing. Below it they are one strip on a line of their own
          (`basis-full`), scrolling sideways within itself — `order-last`
          because the two buttons stay above it whatever the wrap does.
          The scrollbar is hidden, not the scrolling. */}
      <div className="contents max-md:order-last max-md:flex max-md:basis-full max-md:items-center max-md:gap-[8px] max-md:overflow-x-auto max-md:pb-[2px] max-md:[scrollbar-width:none] max-md:[&::-webkit-scrollbar]:hidden">
        <RunFilters workflows={runs.workflows} />
      </div>

      {/* The one primary button in the app: outlined with the accent as
          border and text, never as a fill (10 §Components, §Tokens). */}
      <button
        type="button"
        onClick={onNewRun}
        className={`text-meta cursor-pointer rounded-lg border border-[var(--color-accent-700)] px-[10px] py-[4px] text-[var(--color-accent-200)] hover:border-[var(--color-accent)] hover:bg-[var(--color-accent-900)] ${TOUCH}`}
      >
        <span aria-hidden>＋ </span>new run
      </button>

      {/* The mock's neutral outline beside it: `w`, the palette's row and
          this button are three ways of writing the same parameter. */}
      <button
        type="button"
        onClick={onOpenLibrary}
        className={`text-meta cursor-pointer rounded-lg border border-border px-[10px] py-[4px] text-[var(--color-neutral-400)] hover:border-[var(--color-accent-600)] hover:text-[var(--color-accent-200)] ${TOUCH}`}
      >
        workflows
      </button>

      <FontSizeMenu />

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

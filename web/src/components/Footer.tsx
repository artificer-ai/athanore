/**
 * The footer strip: the key-hint chips and the `^p palette` button
 * (`docs/v1/10-frontend.md` §Layout and §Keyboard).
 *
 * The chips are the rows of `lib/keys.ts` that carry `footer`, in the
 * map's order, so the strip and the `?` overlay that expands it cannot
 * drift: 10 §Overlays calls the overlay "the footer chips, expanded",
 * which is only true while both are drawn from one table. Binding the
 * keys themselves is T067's.
 *
 * Below the breakpoint the chips are hidden — keycaps are noise on a
 * touchscreen, and every key they name stays bound (21 §Narrow layout)
 * — and the palette button is left holding the strip on its own,
 * relabelled `palette` without the `^p` cap and grown to a full-height
 * touch target. It is the touch route to every operator action, because
 * the keyboard map dispatches on the palette's own rows (D176).
 *
 * Beside it, below the breakpoint, sits **`global panes`**: the button
 * that opens and closes the narrow global screen (21 §Regions, narrow,
 * D216). It is in the footer because the footer is the one chrome on
 * every narrow screen and `palette` is the precedent for a full-height
 * touch target there. It is a toggle, `aria-pressed` while the screen
 * is up, and the discoverable route: the swipe that does the same is
 * not one a screen reader has, and 21 §Touch operation lets nothing be
 * reachable only via a gesture. It is drawn on the detail and the
 * global screen — the two narrow screens the swipe joins — and not on
 * the list, which has no gesture to twin (D217 (4)); the shell decides
 * when to pass `global` (D201 (2)), and the class hides the button
 * above the breakpoint regardless, so a desktop render is what it was.
 * It carries no request count — the tab title and the inbox's own
 * header already do.
 */
import type { ReactNode } from 'react'

import { capLabel, FOOTER_HINTS } from '../lib/keys'
import { cn } from '../lib/utils'

/** A keycap chip: neutral-900 on a neutral-800 rule, accent-300 text. */
function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="text-hint rounded-lg border border-border bg-[var(--color-neutral-900)] px-[4px] font-mono text-[var(--color-accent-300)]">
      {children}
    </kbd>
  )
}

export function Footer({
  onOpenPalette,
  global,
}: {
  onOpenPalette: () => void
  /**
   * The narrow global screen's button: whether the screen is up, and
   * what flips it. Absent above the breakpoint, where there is no such
   * screen (D216), and on the narrow list, which has no swipe to it
   * (D217).
   */
  global?: { pressed: boolean; onToggle: () => void } | undefined
}) {
  return (
    <footer className="bg-chrome flex flex-none flex-wrap items-center gap-[12px] border-t border-border px-[12px] py-[5px]">
      {FOOTER_HINTS.map((hint) => (
        <span
          key={hint.id}
          className="inline-flex items-center gap-[5px] max-md:hidden"
        >
          {hint.keys.map((key) => (
            <Kbd key={key}>{capLabel(key)}</Kbd>
          ))}
          <span className="text-hint text-muted-foreground">{hint.label}</span>
        </span>
      ))}

      <div className="flex-1" />

      {global !== undefined && (
        <button
          type="button"
          onClick={global.onToggle}
          aria-pressed={global.pressed}
          className={cn(
            'inline-flex items-center justify-center gap-[6px] rounded-lg border px-[8px] py-[2px] md:hidden max-md:min-h-[24px] max-md:min-w-[24px] max-md:px-[12px]',
            global.pressed
              ? 'border-[var(--color-accent-700)]'
              : 'border-border hover:border-[var(--color-accent-600)]',
          )}
        >
          <span
            className={cn(
              'text-hint',
              global.pressed ? 'text-[var(--color-accent-200)]' : 'text-muted-foreground',
            )}
          >
            global panes
          </span>
        </button>
      )}

      <button
        type="button"
        onClick={onOpenPalette}
        className="inline-flex items-center justify-center gap-[6px] rounded-lg border border-border px-[8px] py-[2px] hover:border-[var(--color-accent-600)] max-md:min-h-[24px] max-md:min-w-[24px] max-md:px-[12px]"
      >
        <span className="text-hint text-[var(--color-accent-300)] max-md:hidden">^p</span>
        <span className="text-hint text-muted-foreground">palette</span>
      </button>
    </footer>
  )
}

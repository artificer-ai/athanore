/**
 * The app's toast surface: Sonner, bottom-right, on Nocturne's surface
 * with a neutral-800 rule.
 *
 * A toast is for what an operator could not have prevented and cannot
 * correct — the `409` that means somebody else answered the request they
 * were looking at (06 §Service). Everything an operator *can* act on is
 * drawn where they are acting: a field's error under the field, a
 * refused node operation in the menu that offered it.
 *
 * **The colours go in through Sonner's own variables.** Its stylesheet
 * paints a toast with `[data-sonner-toast][data-styled=true]`, which two
 * attribute selectors make more specific than any utility class, so
 * `--normal-bg` and friends are the way in and a `bg-…` class would
 * silently lose. The values are the tokens, as everywhere else — nothing
 * here is a hex (10 §Design system).
 *
 * Mounted once, in `app/providers.tsx`, because a second `<Toaster>`
 * would render every toast twice.
 */
import type { CSSProperties } from 'react'
import { Toaster as Sonner } from 'sonner'

/** Sonner's palette, on the Nocturne tokens (10 §Tokens → shadcn). */
const NOCTURNE = {
  '--normal-bg': 'var(--color-surface)',
  '--normal-border': 'var(--color-neutral-800)',
  '--normal-text': 'var(--color-neutral-200)',
  '--border-radius': 'var(--radius)',
} as CSSProperties

export function Toaster() {
  return (
    <Sonner
      position="bottom-right"
      // The app is dark and has no light theme (`src/index.css`), so the
      // toasts are told rather than left to sniff the media query.
      theme="dark"
      style={NOCTURNE}
      toastOptions={{
        classNames: {
          toast: 'text-meta font-mono shadow-[var(--shadow-md)]',
          description: 'text-hint text-muted-foreground',
          actionButton: 'text-[var(--color-accent-200)]',
        },
      }}
    />
  )
}

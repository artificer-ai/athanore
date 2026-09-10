/**
 * Whether the viewport is below the SPA's one breakpoint
 * (`docs/v1/21-design-refresh.md` §Narrow layout, D194).
 *
 * Tailwind's `md`, 768 px, splits the app into its two layouts, and
 * almost all of that split is CSS: a `max-md:` utility is the cheaper
 * and more honest way to say "narrower than this". This hook is for the
 * three places that cannot be a class because they render one subtree
 * or the other — the shell, which shows the run list *or* the detail
 * (`App.tsx`); the pane bar's left slot, which is the back control
 * *instead of* the collapse toggle (`panes/PaneBar.tsx`); and the run
 * list, which draws a two-line row *instead of* a grid row
 * (`components/RunList/RunList.tsx`). D201 (2).
 *
 * The query is written once, here, so the breakpoint the CSS uses and
 * the breakpoint JavaScript uses cannot drift apart. It is expressed as
 * `min-width` — the same direction Tailwind's `md` is — and negated, so
 * that the value it reports is the value the boundary is defined at.
 */
import { useSyncExternalStore } from 'react'

/** Tailwind's `md`: at and above it, 10 §Layout applies unchanged. */
export const WIDE_QUERY = '(min-width: 768px)'

function subscribe(onStoreChange: () => void): () => void {
  const query = window.matchMedia(WIDE_QUERY)
  query.addEventListener('change', onStoreChange)
  return () => {
    query.removeEventListener('change', onStoreChange)
  }
}

function narrowNow(): boolean {
  return !window.matchMedia(WIDE_QUERY).matches
}

export function useIsNarrow(): boolean {
  // `useSyncExternalStore` and not an effect: the first render must
  // already know which layout it is drawing, or a phone would mount the
  // splitter and throw it away a frame later. There is no server render
  // and no hydration here (`main.tsx` calls `createRoot`), so the
  // optional third argument has nothing to answer for.
  return useSyncExternalStore(subscribe, narrowNow)
}

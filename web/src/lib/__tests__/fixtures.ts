/**
 * The viewport a test renders into.
 *
 * jsdom performs no layout and has no window size to speak of, but it
 * does keep `window.innerWidth` — 1024 by default, which is why every
 * test that says nothing renders the desktop layout — and the
 * `matchMedia` of `src/test-setup.ts` answers off it. Setting it and
 * dispatching a `resize` is therefore the whole of "make this a phone",
 * and `useIsNarrow` hears it exactly as it hears a browser's.
 */
import { act } from '@testing-library/react'

/** iPhone-class, the width the mobile gate is pinned to (D197). */
export const NARROW_WIDTH = 390

/** The width jsdom starts at, restored between tests. */
const DEFAULT_WIDTH = 1024

function resizeTo(width: number): void {
  Object.defineProperty(window, 'innerWidth', {
    value: width,
    configurable: true,
    writable: true,
  })
  act(() => {
    window.dispatchEvent(new Event('resize'))
  })
}

/**
 * Render the rest of this test below the breakpoint.
 *
 * Call it before rendering — the shell reads the width on its first
 * render (`lib/useIsNarrow.ts`) — and it undoes itself after the test,
 * so a file may mix narrow cases with desktop ones.
 */
export function narrowViewport(width = NARROW_WIDTH): void {
  resizeTo(width)
}

/** Put the desktop width back: `afterEach` in a file that goes narrow. */
export function wideViewport(): void {
  resizeTo(DEFAULT_WIDTH)
}

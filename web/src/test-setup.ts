// Testing Library's DOM matchers, and a clean document between tests.
import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

/**
 * jsdom implements no `ResizeObserver`, and `react-resizable-panels`
 * constructs one for every mounted `Group` (`components/Splitter.tsx`) —
 * without this, rendering the shell throws before a single assertion.
 *
 * It observes nothing, which is the truth of the environment: jsdom
 * performs no layout, so no element here ever changes size. A test that
 * needs a geometry states one itself, as the splitter's does.
 */
class NoLayoutResizeObserver implements ResizeObserver {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

globalThis.ResizeObserver ??= NoLayoutResizeObserver

afterEach(cleanup)

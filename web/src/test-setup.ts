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

/**
 * jsdom implements no `EventSource`, and `Providers` opens one for the
 * event feed on mount (`src/realtime/sse.ts`) — without this, rendering
 * anything inside the providers throws.
 *
 * It connects to nothing and dispatches nothing, which is the truth of
 * the environment: jsdom has no network here. A test that wants to drive
 * a feed passes `EventFeed` its own `open`, as `realtime/sse.test.ts`
 * does, rather than reaching for this.
 */
class InertEventSource implements Partial<EventSource> {
  static readonly CONNECTING = 0
  static readonly OPEN = 1
  static readonly CLOSED = 2

  readonly readyState = InertEventSource.CONNECTING
  readonly url: string

  constructor(url: string) {
    this.url = url
  }

  addEventListener(): void {}
  removeEventListener(): void {}
  dispatchEvent(): boolean {
    return false
  }
  close(): void {}
}

globalThis.EventSource ??= InertEventSource as unknown as typeof EventSource

afterEach(cleanup)

/**
 * jsdom implements no `fetch`, so the `Request` a test meets is node's,
 * and node's has no document to resolve a relative URL against: the API
 * client is configured with `baseUrl: ""` (`src/api/client.ts`), which
 * is exactly what a browser resolves against the page and node rejects
 * as `ERR_INVALID_URL`.
 *
 * Resolving against `window.location` here is what the browser does,
 * which keeps the tests on the client's real configuration rather than
 * on an absolute base no deployment uses.
 */
class DocumentRelativeRequest extends Request {
  constructor(input: RequestInfo | URL, init?: RequestInit) {
    super(
      typeof input === 'string' ? new URL(input, window.location.href) : input,
      init,
    )
  }
}

globalThis.Request = DocumentRelativeRequest

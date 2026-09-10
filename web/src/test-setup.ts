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

/**
 * jsdom implements no `Element.scrollIntoView`, and cmdk calls it on
 * every selection change to keep the highlighted row in view
 * (`overlays/Palette.tsx`) — without this, an arrow key in the palette
 * throws.
 *
 * It scrolls nothing, which is the truth of the environment: jsdom
 * performs no layout, so nothing here is ever out of view.
 */
Element.prototype.scrollIntoView ??= function scrollIntoView() {}

/**
 * jsdom implements no `window.matchMedia`, and the SPA asks it which of
 * its two layouts it is drawing (`lib/useIsNarrow.ts`) — without this,
 * rendering the shell throws.
 *
 * It answers `(min-width: Npx)` and `(max-width: Npx)` off
 * `window.innerWidth`, which jsdom does keep (1024 by default, so every
 * test that says nothing is a desktop test), and re-answers on `resize`.
 * A test that wants the narrow layout sets `window.innerWidth` and
 * dispatches one, which is what `narrowViewport()` does
 * (`lib/__tests__/fixtures.ts`).
 */
const WIDTH_QUERY = /\((min|max)-width:\s*(\d+)px\)/

function matches(query: string): boolean {
  const parsed = WIDTH_QUERY.exec(query)
  if (parsed === null) return false
  const px = Number(parsed[2])
  return parsed[1] === 'min' ? window.innerWidth >= px : window.innerWidth <= px
}

class WidthQueryList extends EventTarget implements Partial<MediaQueryList> {
  readonly media: string

  constructor(media: string) {
    super()
    this.media = media
    // One listener per list, dropped with the list: jsdom builds a new
    // window per test file, and nothing here outlives it.
    window.addEventListener('resize', () => {
      this.dispatchEvent(new Event('change'))
    })
  }

  get matches(): boolean {
    return matches(this.media)
  }
}

globalThis.matchMedia ??= ((query: string) =>
  new WidthQueryList(query)) as typeof matchMedia

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

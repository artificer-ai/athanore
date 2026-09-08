/**
 * One `EventSource` per tab, and everything that keeps a tab open for a
 * week honest (`docs/v1/10-frontend.md` §Realtime and caching, 08
 * §Events).
 *
 * The SPA opens exactly one stream and fans it out through
 * {@link Invalidator}: a second `EventSource` per component would be a
 * second replay, a second keep-alive and a second reconnect storm for
 * the same frames. Nothing here polls.
 *
 * What the wrapper adds over the browser's own reconnect:
 *
 * - **the cursor.** Every stored frame carries `id:`; ephemeral ones
 *   (`task.stream`) do not (08), so the last id seen always names a row
 *   the server can replay from. The reconnect carries it as `after=`,
 *   which is the same cursor the browser would have sent as
 *   `Last-Event-ID` — made explicit because we close and reopen the
 *   stream ourselves rather than letting the browser retry blind.
 * - **the backoff.** 1 s doubling to 30 s. A server that is restarting
 *   is back within the first second or two; one that is gone should not
 *   be asked sixty times a minute.
 * - **the restart check.** A stream that comes back may be a different
 *   process. `/api/me` is refetched on every reconnect and, if
 *   `started_at` moved, so is `/api/plugins`: the manifest changes only
 *   on restart, so there is no event for it (09 §Wire contract).
 * - **`resync`.** The server sends it when a replay would exceed
 *   `sse_replay_cap` (08). Everything this tab holds may be stale and
 *   there is no cursor worth keeping, so the cache is invalidated whole
 *   and the next connection starts from the live edge.
 */
import type { QueryClient } from '@tanstack/react-query'

import { API_BASE_URL, meQueryOptions } from '../api/client'
import { manifestApiPluginsGetQueryKey } from '../api/gen/@tanstack/react-query.gen'
import type { EventName, Me } from '../api/gen/types.gen'
import { usePrefs } from '../store/prefs'
import { useUi, type FeedStatus } from '../store/ui'
import { Invalidator, subscribeRefreshOn, type AthanoreEvent } from './invalidate'

/** The stream (08 §Events). Excluded from the generated client (D135). */
export const EVENTS_PATH = '/api/events'

/** The frame that says "your cursor is too old; refetch everything". */
export const RESYNC = 'resync'

/** The first reconnect delay, and the ceiling it doubles up to (10). */
export const RECONNECT_MIN_MS = 1000
export const RECONNECT_MAX_MS = 30000

/**
 * How many attempts must fail before the operator is told.
 *
 * One failure is a dropped connection, which a browser suffers routinely
 * and recovers from inside a second; announcing it would put a banner on
 * screen more often than it means anything. Two means nothing answered
 * for the second and a half either side of a retry, which is a server
 * that is not there.
 */
export const DOWN_AFTER_FAILURES = 2

/**
 * Every event name the contract defines, as a value.
 *
 * A browser's `EventSource` delivers a named frame *only* to a listener
 * registered for that name — there is no wildcard — so the feed needs
 * the list at runtime, and `EventName` is a type. Writing it as the keys
 * of a `Record<EventName, true>` is what makes the two agree: a name
 * added to the wire contract fails this file's typecheck as a missing
 * key, and a name removed fails it as an excess one.
 */
const EVENT_NAME_TABLE: Record<EventName, true> = {
  'run.created': true,
  'run.started': true,
  'run.updated': true,
  'run.reordered': true,
  'run.paused': true,
  'run.resumed': true,
  'run.cancelled': true,
  'run.deleted': true,
  'run.completed': true,
  'run.failed': true,
  'task.enqueued': true,
  'join.arrived': true,
  'task.started': true,
  'task.done': true,
  'task.failed': true,
  'task.dead_lettered': true,
  'task.waiting': true,
  'task.resumed': true,
  'task.cancelled': true,
  'task.moved': true,
  'task.status_set': true,
  'task.stream': true,
  'submission.accepted': true,
  'submission.rejected': true,
  'submission.repair': true,
  'request.opened': true,
  'request.answered': true,
  'log.appended': true,
  'agent.stats': true,
  'engine.recovered': true,
  'engine.stopping': true,
}

/** The names the feed subscribes to before any plugin is loaded. */
export const EVENT_NAMES: readonly string[] = Object.keys(EVENT_NAME_TABLE)

/**
 * The part of `EventSource` this wrapper uses.
 *
 * Narrowed to what is needed so that a test can drive the feed without a
 * browser: jsdom implements no `EventSource` at all.
 */
export type EventSourceLike = {
  addEventListener: (type: string, listener: (event: Event) => void) => void
  close: () => void
}

export type EventFeedOptions = {
  /** Open the stream. Injected by tests; the default is the browser's. */
  open?: (url: string) => EventSourceLike
  /** Where the feed's state goes. The default is the `useUi` store. */
  onState?: (status: FeedStatus, retryAt: number | null) => void
}

/** The browser's own `EventSource`, which is what ships. */
function openEventSource(url: string): EventSourceLike {
  return new EventSource(url)
}

function publishToStore(status: FeedStatus, retryAt: number | null): void {
  useUi.getState().setFeed({ status, retryAt })
}

/**
 * The tab's connection to `GET /api/events`.
 *
 * Built with the query client whose cache it keeps fresh; `start()` opens
 * the stream and `stop()` closes it for good.
 */
export class EventFeed {
  readonly #queryClient: QueryClient
  readonly #open: (url: string) => EventSourceLike
  readonly #onState: (status: FeedStatus, retryAt: number | null) => void
  readonly #invalidator: Invalidator
  readonly #names = new Set<string>(EVENT_NAMES)

  #source: EventSourceLike | null = null
  #timer: ReturnType<typeof setTimeout> | null = null
  #unsubscribe: (() => void)[] = []
  #status: FeedStatus = 'reconnecting'
  #lastId: string | null = null
  #failures = 0
  #opened = false
  #started = false

  constructor(queryClient: QueryClient, options: EventFeedOptions = {}) {
    this.#queryClient = queryClient
    this.#open = options.open ?? openEventSource
    this.#onState = options.onState ?? publishToStore
    this.#invalidator = new Invalidator(queryClient)
  }

  /** What the feed is doing right now. */
  get status(): FeedStatus {
    return this.#status
  }

  /** The last stored event id seen, which the next connect replays from. */
  get lastId(): string | null {
    return this.#lastId
  }

  /**
   * Open the stream and keep it open.
   *
   * Idempotent: React mounts an effect twice under `StrictMode`, and a
   * second stream would be a second replay of everything.
   */
  start(): void {
    if (this.#started) return
    this.#started = true

    this.#unsubscribe.push(
      // A plugin's own event names are only known once its manifest has
      // been read, and a listener is per name (09, `invalidate.ts`).
      subscribeRefreshOn((names) => {
        for (const name of names) this.watch(name)
      }),
      // The credential changed — the operator answered the token screen
      // — so the refusal that closed this stream may no longer apply.
      // Waiting out a 30 s backoff would leave the app dead after a
      // login that plainly worked.
      usePrefs.subscribe((state, previous) => {
        if (state.token !== previous.token && this.#status !== 'open') {
          this.reconnectNow()
        }
      }),
    )

    this.#connect()
  }

  /** Close the stream and stop reconnecting. */
  stop(): void {
    this.#started = false
    this.#clearTimer()
    this.#closeSource()
    this.#invalidator.dispose()
    for (const unsubscribe of this.#unsubscribe) unsubscribe()
    this.#unsubscribe = []
  }

  /** Deliver one more event name to the invalidation table. */
  watch(name: string): void {
    if (this.#names.has(name)) return
    this.#names.add(name)
    this.#source?.addEventListener(name, this.#onFrame)
  }

  /** Try again now rather than when the backoff says so. */
  reconnectNow(): void {
    if (!this.#started) return
    this.#clearTimer()
    this.#connect()
  }

  #connect(): void {
    this.#closeSource()
    const source = this.#open(this.#url())
    this.#source = source
    source.addEventListener('open', this.#onOpen)
    source.addEventListener('error', this.#onError)
    source.addEventListener(RESYNC, this.#onResync)
    for (const name of this.#names) source.addEventListener(name, this.#onFrame)
    this.#publish(this.#status, null)
  }

  /**
   * `/api/events`, with the cursor and — only where 08 §Auth allows one
   * — the operator token.
   *
   * This is the one place a credential legitimately rides in a query
   * string: `EventSource` cannot set a header. The rule for sending it
   * is the API client's, so the two cannot disagree — everything but a
   * server that has answered `auth: "off"` (D154).
   */
  #url(): string {
    const params = new URLSearchParams()
    if (this.#lastId !== null) params.set('after', this.#lastId)

    const me = this.#queryClient.getQueryData<Me>(meQueryOptions().queryKey)
    const token = usePrefs.getState().token
    if (token !== null && me?.auth !== 'off') params.set('access_token', token)

    const query = params.toString()
    return query === ''
      ? `${API_BASE_URL}${EVENTS_PATH}`
      : `${API_BASE_URL}${EVENTS_PATH}?${query}`
  }

  #onOpen = (): void => {
    const reconnected = this.#opened
    this.#opened = true
    this.#failures = 0
    this.#publish('open', null)
    if (reconnected) void this.#afterReconnect()
  }

  /**
   * The stream came back. It may be a different server: `/api/me` says
   * when this one started, and a `started_at` that moved means the
   * plugin manifest may no longer be the one this tab is rendering (09).
   */
  async #afterReconnect(): Promise<void> {
    const meKey = meQueryOptions().queryKey
    const before = this.#queryClient.getQueryData<Me>(meKey)?.started_at
    try {
      await this.#queryClient.refetchQueries({ queryKey: meKey })
      const after = this.#queryClient.getQueryData<Me>(meKey)?.started_at
      if (before !== undefined && after !== undefined && before !== after) {
        await this.#queryClient.refetchQueries({
          queryKey: manifestApiPluginsGetQueryKey(),
        })
      }
    } catch {
      // The refetch failed because the server went away again, which the
      // stream is about to report by itself. Nothing to add.
    }
  }

  #onError = (): void => {
    // `EventSource` retries on its own, blind and on the server's
    // `retry:`. We take it over so the next attempt carries `after=`.
    this.#closeSource()
    this.#failures += 1

    const delay = Math.min(
      RECONNECT_MAX_MS,
      RECONNECT_MIN_MS * 2 ** (this.#failures - 1),
    )
    const status = this.#failures >= DOWN_AFTER_FAILURES ? 'down' : 'reconnecting'
    this.#publish(status, Date.now() + delay)

    this.#clearTimer()
    this.#timer = setTimeout(() => {
      this.#timer = null
      this.#connect()
    }, delay)
  }

  #onResync = (): void => {
    // The replay was capped: what this tab holds may be missing anything
    // at all, and the cursor it holds names an event the server will no
    // longer serve from (08). Everything is stale and the next connect
    // starts at the live edge.
    this.#lastId = null
    this.#invalidator.dispose()
    void this.#queryClient.invalidateQueries()
  }

  #onFrame = (event: Event): void => {
    const message = event as MessageEvent<string>
    // Only stored events carry an id; `task.stream` deliberately does
    // not, so the cursor always names a row that can be replayed (08).
    if (message.lastEventId !== undefined && message.lastEventId !== '') {
      this.#lastId = message.lastEventId
    }

    let payload: unknown
    try {
      payload = JSON.parse(message.data) as unknown
    } catch {
      console.warn('athanore: an SSE frame carried no JSON', message.data)
      return
    }

    const envelope = payload as AthanoreEvent
    if (typeof envelope?.name !== 'string') {
      console.warn('athanore: an SSE frame carried no event name', payload)
      return
    }

    this.#invalidator.handle(envelope)
  }

  #publish(status: FeedStatus, retryAt: number | null): void {
    this.#status = status
    this.#onState(status, retryAt)
  }

  #clearTimer(): void {
    if (this.#timer !== null) {
      clearTimeout(this.#timer)
      this.#timer = null
    }
  }

  #closeSource(): void {
    this.#source?.close()
    this.#source = null
  }
}

/**
 * The tab's feed, as `src/api/client.ts` holds the tab's fetch client.
 *
 * One `EventSource` per tab is the design (10 §Realtime), so there is
 * one of these and everything that needs it — the banner's `try now`,
 * a plugin host wanting one more event name — asks for it here rather
 * than being handed it through the tree.
 */
let current: EventFeed | null = null

/**
 * Build the tab's feed, replacing any earlier one.
 *
 * The old feed is stopped rather than left running: a second stream
 * would replay everything a second time, and under `StrictMode` the
 * mount that creates this one has already discarded the other.
 */
export function createAppEventFeed(
  queryClient: QueryClient,
  options: EventFeedOptions = {},
): EventFeed {
  current?.stop()
  current = new EventFeed(queryClient, options)
  return current
}

/** The tab's feed, or `null` before one has been made. */
export function appEventFeed(): EventFeed | null {
  return current
}

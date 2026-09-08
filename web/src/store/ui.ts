/**
 * `useUi` — client state that is deliberately *not* persisted and
 * deliberately not in the URL.
 *
 * Which region has the operator's attention is neither worth a link nor
 * worth remembering across a reload: it is where the next keystroke goes
 * (`docs/v1/10-frontend.md` §Keyboard — `tab` moves it, `⏎` sends it to
 * the detail pane). It starts on the run list, which is where a fresh
 * page's first `↑`/`↓` should land.
 *
 * Whether the operator has to produce a token belongs here for the same
 * reason: it is a fact about this tab's conversation with the server,
 * true until the next answer from it, and a reload asks again rather
 * than remembering (`docs/v1/10-frontend.md` §Auth in the browser).
 *
 * So does the state of that tab's event stream, which is the same kind
 * of fact and reaches the store the same way — the feed writes it, as
 * the API client's 401 interceptor writes `needsToken`, and the header
 * and the banner read it (`src/realtime/sse.ts`).
 */
import { create } from 'zustand'

/** The two regions that take focus: the run list and the detail pane. */
export type FocusRegion = 'list' | 'detail'

/** The workflow chip that means "do not filter by workflow" (10 §Layout). */
export const ALL_WORKFLOWS = 'all'

/**
 * What the run list is filtered to: the header's chip and its `/` input.
 *
 * Both are client-side (T061): `GET /api/runs` takes `?status` and
 * `?workflow`, but a run list is small and returns whole (08
 * §Conventions), so narrowing it in the browser costs one array pass and
 * keeps the one cached copy of the resource that the invalidation table
 * refreshes. They are not search parameters either: 10 §Layout's list of
 * what makes a view *that view* is `run`, `pane`, `overlay` and `task`,
 * and `src/routes/search.ts` drops everything else.
 *
 * `workflow` is {@link ALL_WORKFLOWS} or a workflow name; `query` is the
 * raw text, matched against a row's title and id.
 */
export type RunFilter = {
  workflow: string
  query: string
}

/**
 * Whether this tab is hearing from the server (`src/realtime/sse.ts`).
 *
 * `reconnecting` is a stream that dropped and is coming back, which is
 * ordinary and says nothing on screen; `down` is one that has failed to
 * come back and is what greys the header's counts and raises the banner
 * (10 §Realtime and caching).
 */
export type FeedStatus = 'open' | 'reconnecting' | 'down'

/** The feed's state: what it is doing, and when it next tries. */
export type Feed = {
  status: FeedStatus
  /** When the next connection attempt is due, in epoch milliseconds. */
  retryAt: number | null
}

export type Ui = {
  focus: FocusRegion
  setFocus: (focus: FocusRegion) => void
  /** `tab`: move focus to the other region. */
  toggleFocus: () => void

  /**
   * Whether the operator token screen is what the app should be showing.
   *
   * The API client's 401 interceptor raises it (`src/api/client.ts`):
   * any operator request the server refused means the token this browser
   * holds is missing or no longer good, whichever endpoint found out.
   * `AppGate` also raises it from `/api/me` alone, without a refusal,
   * when the server says it wants a token and this caller has none.
   */
  needsToken: boolean
  setNeedsToken: (needsToken: boolean) => void

  /**
   * The event feed's state. It starts `reconnecting` because that is
   * what a stream nobody has opened yet is: `open` would be a claim the
   * page has not earned, and `down` would raise a banner over a server
   * that is answering perfectly well.
   */
  feed: Feed
  setFeed: (feed: Feed) => void

  /** The run list's chip and `/` input (T061). */
  runFilter: RunFilter
  setRunWorkflow: (workflow: string) => void
  setRunQuery: (query: string) => void
}

export const useUi = create<Ui>()((set) => ({
  focus: 'list',
  setFocus: (focus) => set({ focus }),
  toggleFocus: () =>
    set((state) => ({ focus: state.focus === 'list' ? 'detail' : 'list' })),

  needsToken: false,
  setNeedsToken: (needsToken) => set({ needsToken }),

  feed: { status: 'reconnecting', retryAt: null },
  setFeed: (feed) => set({ feed }),

  runFilter: { workflow: ALL_WORKFLOWS, query: '' },
  setRunWorkflow: (workflow) =>
    set((state) => ({ runFilter: { ...state.runFilter, workflow } })),
  setRunQuery: (query) => set((state) => ({ runFilter: { ...state.runFilter, query } })),
}))

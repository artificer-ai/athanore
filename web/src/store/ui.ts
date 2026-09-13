/**
 * `useUi` — client state that is deliberately *not* persisted and
 * deliberately not in the URL.
 *
 * Which region has the operator's attention is neither worth a link nor
 * worth remembering across a reload: it is where the next keystroke goes
 * (`tab` moves it). It starts on the run list, which is where a fresh
 * page's first `↑`/`↓` should land.
 *
 * `focusedRun` is the same kind of fact one step in: the run `⏎` has
 * picked up, so that `↑`/`↓` move it in the dispatch order instead of
 * moving the selection (10 §Keyboard, D204). It is a mode the operator
 * is in for a keystroke or two, not a view worth linking to — and the
 * run it names is already in the URL, as `?run=`.
 *
 * Whether the operator has to produce a token belongs here for the same
 * reason: it is a fact about this tab's conversation with the server,
 * true until the next answer from it, and a reload asks again rather
 * than remembering.
 *
 * So does the state of that tab's event stream, which is the same kind
 * of fact and reaches the store the same way — the feed writes it, as
 * the API client's 401 interceptor writes `needsToken`, and the header
 * and the banner read it (`src/realtime/sse.ts`).
 *
 * And so does `logComposerFor`, for the first reason rather than the
 * second: `append log` moves the caret, which is where the next
 * keystroke goes, and the palette command that asks for it and the
 * composer that takes it are the shell and a pane inside a pane, with no
 * prop between them that is about focus.
 *
 * `staleAssets` is a fact about *this document* and nothing else: which
 * plugins' JavaScript the manifest now lists at a content version this
 * page already ran another of (22 §SPA). The manifest reader writes it,
 * as the feed writes `feed`, and the banner reads it. It is never
 * cleared, because nothing but a reload makes a document with the new
 * module in it — and a reload starts the store over (D253).
 */
import { create } from 'zustand'

import type { RunStatus } from '../api/gen/types.gen'

/** The two regions that take focus: the run list and the detail pane. */
export type FocusRegion = 'list' | 'detail'

/** The workflow chip that means "do not filter by workflow" (10 §Layout). */
export const ALL_WORKFLOWS = 'all'

/** Every run status of 03, in the order the status chips are drawn. */
export const RUN_STATUSES: readonly RunStatus[] = [
  'queued',
  'running',
  'paused',
  'completed',
  'failed',
  'cancelled',
]

/**
 * The statuses on at load: everything that is not finished (D268).
 *
 * `failed` is on deliberately: a failed run is unfinished business, the
 * thing an operator retries or reruns (04), and hiding it would hide the
 * one status that most needs a look.
 */
export const DEFAULT_RUN_STATUSES: readonly RunStatus[] = [
  'queued',
  'running',
  'paused',
  'failed',
]

/**
 * What the run list is filtered to: the header's chips and its `/` input.
 *
 * All of it is client-side (T061): `GET /api/runs` takes `?status` and
 * `?workflow`, but a run list is small and returns whole (08
 * §Conventions), so narrowing it in the browser costs one array pass and
 * keeps the one cached copy of the resource that the invalidation table
 * refreshes. They are not search parameters either: 10 §Layout's list of
 * what makes a view *that view* is `run`, `pane`, `overlay` and `task`,
 * and `src/routes/search.ts` drops everything else.
 *
 * `workflow` is {@link ALL_WORKFLOWS} or a workflow name; `statuses` is
 * the set a run may have and still be listed (OR within it, and every
 * one of them may be off); `query` is the raw text, matched against a
 * row's id prefix, its title and its workflow name, case-insensitively.
 * A run is shown when all three agree — AND across the kinds.
 *
 * The default is {@link DEFAULT_RUN_FILTER}: every workflow, the four
 * unfinished statuses, no query. Because this store is not persisted,
 * that default is what every load starts from (D268).
 */
export type RunFilter = {
  workflow: string
  /** The statuses a run may have and still be listed (OR within). */
  statuses: RunStatus[]
  query: string
}

/** What every load starts from, and what a submitted run resets to. */
export const DEFAULT_RUN_FILTER: RunFilter = {
  workflow: ALL_WORKFLOWS,
  statuses: [...DEFAULT_RUN_STATUSES],
  query: '',
}

/** A copy of the default, so nothing that mutates the store shares it. */
function defaultRunFilter(): RunFilter {
  return { ...DEFAULT_RUN_FILTER, statuses: [...DEFAULT_RUN_FILTER.statuses] }
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
   * The run `⏎` has picked up, or `null` (10 §Keyboard).
   *
   * An id and not a boolean, so that the shell can say *which* run is
   * held and check it against the selection: focus is only ever on the
   * selected run, and a held id that stops being `?run=` — or whose row
   * a filter, a delete or a narrow viewport takes off the screen — is
   * put down rather than left under the arrow keys (D204 (2)).
   */
  focusedRun: string | null
  /** `⏎`: pick this run up. */
  focusRun: (runId: string) => void
  /** `⏎` again, `esc`, or the row leaving the screen: put it down. */
  blurRun: () => void

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

  /** The run list's chips and `/` input (T061, D268). */
  runFilter: RunFilter
  setRunWorkflow: (workflow: string) => void
  /**
   * The status chips that are on. Takes what Radix hands back — a
   * `string[]` — and keeps only the statuses, in chip order, so the
   * stored array never holds a value that is not a status and never
   * depends on the order the chips were pressed in.
   */
  setRunStatuses: (statuses: readonly string[]) => void
  setRunQuery: (query: string) => void
  /** A run was submitted, or the default is wanted back. */
  resetRunFilter: () => void

  /**
   * The run whose log composer has been asked for the caret, or `null`.
   *
   * `append log` is a palette command and a key (`l`, 10 §Keyboard), and
   * what it does is put the operator in the box the log pane already
   * has: the shell moves the pane cycle to the log and asks for the
   * caret, and the composer — which is mounted by the pane, one level
   * below anything the shell holds — takes it and clears the request.
   *
   * It is one request and not a flag, and it names the run it was made
   * for: a composer belonging to another run leaves it alone, so a
   * request that was never served cannot steal the caret from a pane the
   * operator opened for something else.
   */
  logComposerFor: string | null
  /** `l`: ask this run's composer for the caret. */
  focusLogComposer: (runId: string) => void
  /** The composer has taken it; there is nothing left to serve. */
  clearLogComposer: () => void

  /**
   * Workflow → the manifest URLs this document cannot follow (22 §SPA).
   *
   * A workflow is a key here once the manifest has listed, for it, a
   * URL whose path this document injected under a different `?v=`
   * (`plugins/assets.ts`). The banner draws the keys; the URLs are what
   * it is about, kept so a later manifest for the same workflow merges
   * in rather than overwriting what an earlier one found.
   */
  staleAssets: Record<string, readonly string[]>
  /** The manifest reader found `urls` stale for `workflow`: merge them in. */
  markStaleAssets: (workflow: string, urls: readonly string[]) => void
}

export const useUi = create<Ui>()((set) => ({
  focus: 'list',
  setFocus: (focus) => set({ focus }),
  toggleFocus: () =>
    set((state) => ({ focus: state.focus === 'list' ? 'detail' : 'list' })),

  focusedRun: null,
  focusRun: (runId) => set({ focusedRun: runId }),
  blurRun: () => set({ focusedRun: null }),

  needsToken: false,
  setNeedsToken: (needsToken) => set({ needsToken }),

  feed: { status: 'reconnecting', retryAt: null },
  setFeed: (feed) => set({ feed }),

  runFilter: defaultRunFilter(),
  setRunWorkflow: (workflow) =>
    set((state) => ({ runFilter: { ...state.runFilter, workflow } })),
  setRunStatuses: (statuses) =>
    set((state) => ({
      runFilter: {
        ...state.runFilter,
        statuses: RUN_STATUSES.filter((status) => statuses.includes(status)),
      },
    })),
  setRunQuery: (query) => set((state) => ({ runFilter: { ...state.runFilter, query } })),
  resetRunFilter: () => set({ runFilter: defaultRunFilter() }),

  logComposerFor: null,
  focusLogComposer: (runId) => set({ logComposerFor: runId }),
  clearLogComposer: () => set({ logComposerFor: null }),

  staleAssets: {},
  markStaleAssets: (workflow, urls) =>
    set((state) => {
      const known = state.staleAssets[workflow] ?? []
      const added = urls.filter((url) => !known.includes(url))
      if (added.length === 0) return state
      return {
        staleAssets: { ...state.staleAssets, [workflow]: [...known, ...added] },
      }
    }),
}))

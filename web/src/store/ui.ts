/**
 * `useUi` — client state that is deliberately *not* persisted and
 * deliberately not in the URL.
 *
 * Which region has the operator's attention is neither worth a link nor
 * worth remembering across a reload: it is where the next keystroke goes
 * (`tab` moves it). It starts on the run list, which is where a fresh
 * page's first `↑`/`↓` should land.
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

/**
 * What the run list is filtered to: one field per filterable column.
 *
 * The column headers write every field but `workflows`, which the
 * workflow library's marks write (10 §Layout, §Overlays, D275). Each
 * field is empty when its column does not filter, and the fields are
 * ANDed: a run is shown when it passes every one of them.
 *
 * All of it is client-side (T061): `GET /api/runs` takes `?status` and
 * `?workflow`, but a run list is small and returns whole (08
 * §Conventions), so narrowing it in the browser costs one array pass and
 * keeps the one cached copy of the resource that the invalidation table
 * refreshes. None of it is a search parameter either: 10 §Layout's list
 * of what makes a view *that view* is `run`, `pane`, `overlay` and
 * `task`, and `src/routes/search.ts` drops everything else.
 */
export type RunFilter = {
  /** RUN: text the run's id contains, case-folded. */
  id: string
  /** TITLE: text the run's title contains, case-folded. */
  title: string
  /** WORKFLOW: the workflows a run may be of; empty is any. */
  workflows: readonly string[]
  /** STATUS: the statuses a run may be in; empty is any. */
  statuses: readonly RunStatus[]
  /**
   * NODE: the nodes a run may be in, {@link NO_NODE_FILTER} standing for
   * a run in none; empty is any.
   */
  nodes: readonly string[]
  /**
   * AGE, as a rolling window: created within this many milliseconds of
   * now, or `null`. A preset writes it, and it moves with the clock, so
   * `last 1h` means the last hour for as long as it stays on.
   */
  within: number | null
  /**
   * AGE, as a fixed range: created at or after this local
   * `datetime-local` value (`YYYY-MM-DDTHH:mm`), or `''`.
   */
  after: string
  /** …and within the minute this one names, or `''`. */
  before: string
}

/** The NODE filter's value for a run that is in no node. */
export const NO_NODE_FILTER = ''

/** A filter that shows every run. */
export const EMPTY_RUN_FILTER: RunFilter = {
  id: '',
  title: '',
  workflows: [],
  statuses: [],
  nodes: [],
  within: null,
  after: '',
  before: '',
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

  /** The run list's column filters and the library's marks (D275). */
  runFilter: RunFilter
  /** Change some of the filter's fields and leave the rest. */
  setRunFilter: (patch: Partial<RunFilter>) => void
  /** Show every run again. */
  clearRunFilter: () => void

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

  needsToken: false,
  setNeedsToken: (needsToken) => set({ needsToken }),

  feed: { status: 'reconnecting', retryAt: null },
  setFeed: (feed) => set({ feed }),

  runFilter: EMPTY_RUN_FILTER,
  setRunFilter: (patch) =>
    set((state) => ({ runFilter: { ...state.runFilter, ...patch } })),
  clearRunFilter: () => set({ runFilter: EMPTY_RUN_FILTER }),

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

/**
 * `usePrefs` — the operator's own settings, persisted to `localStorage`.
 *
 * The split against the URL is the one `docs/v1/10-frontend.md` §Layout
 * draws: what makes a view *that view* goes in the search params
 * (`src/routes/search.ts`), and what is personal to this browser lives
 * here. A list width is not worth putting in a link; a selected run is.
 *
 * The token is here rather than in a cookie because 10 §Auth in the
 * browser says so: on a network bind the SPA stores the operator token
 * in `localStorage` and sends it as a bearer header (T059, T065). On the
 * default loopback deployment it stays `null` and is never sent.
 */
import { create } from 'zustand'
import { persist } from 'zustand/middleware'

/** The run list's narrowest useful width, in pixels (10 §Layout). */
export const MIN_LIST_WIDTH = 260

/**
 * What the detail pane keeps for itself: the run list may grow to
 * `window − 340` and no further (10 §Layout).
 */
export const MIN_DETAIL_WIDTH = 340

/** The mock's default run-list width. */
export const DEFAULT_LIST_WIDTH = 540

/** The run list's widest: `window − 340`, never below its own minimum. */
function maxListWidth(viewport: number): number {
  return Math.max(MIN_LIST_WIDTH, viewport - MIN_DETAIL_WIDTH)
}

/**
 * Clamp a run-list width to 10 §Layout's two ends: never below
 * {@link MIN_LIST_WIDTH}, never above `viewportWidth − MIN_DETAIL_WIDTH`.
 *
 * On a viewport too narrow for both bounds to hold the minimum wins, so
 * the list is never clamped to something smaller than it can render.
 */
export function clampListWidth(width: number, viewport: number): number {
  if (!Number.isFinite(width)) return DEFAULT_LIST_WIDTH
  const max = maxListWidth(viewport)
  return Math.round(Math.min(Math.max(width, MIN_LIST_WIDTH), max))
}

/** The current viewport width, or a wide fallback outside a browser. */
function viewportWidth(): number {
  return typeof window === 'undefined' ? Number.POSITIVE_INFINITY : window.innerWidth
}

export type Prefs = {
  /** Run-list width in pixels; the splitter writes it as it is dragged. */
  listWidth: number
  /** Whether the run list is collapsed to the 30 px `RUNS n` rail. */
  listCollapsed: boolean
  /**
   * Switch the pane to `agent` once when a new request arrives on the
   * selected run (10 §Attention). On by default; this is the opt-out.
   */
  autoSwitchOnRequest: boolean
  /** Desktop notifications, opt-in (10 §Attention). */
  notifications: boolean
  /** The operator token, or `null` on a deployment that needs none. */
  token: string | null

  setListWidth: (width: number) => void
  setListCollapsed: (collapsed: boolean) => void
  toggleListCollapsed: () => void
  setAutoSwitchOnRequest: (on: boolean) => void
  setNotifications: (on: boolean) => void
  setToken: (token: string | null) => void
}

/** The `localStorage` key. Namespaced so a shared origin cannot collide. */
export const PREFS_STORAGE_KEY = 'athanore.prefs'

export const usePrefs = create<Prefs>()(
  persist(
    (set) => ({
      listWidth: DEFAULT_LIST_WIDTH,
      listCollapsed: false,
      autoSwitchOnRequest: true,
      notifications: false,
      token: null,

      setListWidth: (width) =>
        set({ listWidth: clampListWidth(width, viewportWidth()) }),
      setListCollapsed: (listCollapsed) => set({ listCollapsed }),
      toggleListCollapsed: () =>
        set((state) => ({ listCollapsed: !state.listCollapsed })),
      setAutoSwitchOnRequest: (autoSwitchOnRequest) => set({ autoSwitchOnRequest }),
      setNotifications: (notifications) => set({ notifications }),
      setToken: (token) => set({ token }),
    }),
    {
      name: PREFS_STORAGE_KEY,
      // Only the five values of T058 are persisted; the actions are
      // rebuilt from the module on every load.
      partialize: (state) => ({
        listWidth: state.listWidth,
        listCollapsed: state.listCollapsed,
        autoSwitchOnRequest: state.autoSwitchOnRequest,
        notifications: state.notifications,
        token: state.token,
      }),
    },
  ),
)

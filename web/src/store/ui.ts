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
 */
import { create } from 'zustand'

/** The two regions that take focus: the run list and the detail pane. */
export type FocusRegion = 'list' | 'detail'

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
}

export const useUi = create<Ui>()((set) => ({
  focus: 'list',
  setFocus: (focus) => set({ focus }),
  toggleFocus: () =>
    set((state) => ({ focus: state.focus === 'list' ? 'detail' : 'list' })),

  needsToken: false,
  setNeedsToken: (needsToken) => set({ needsToken }),
}))

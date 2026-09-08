/**
 * `useUi` — client state that is deliberately *not* persisted and
 * deliberately not in the URL.
 *
 * Which region has the operator's attention is neither worth a link nor
 * worth remembering across a reload: it is where the next keystroke goes
 * (`docs/v1/10-frontend.md` §Keyboard — `tab` moves it, `⏎` sends it to
 * the detail pane). It starts on the run list, which is where a fresh
 * page's first `↑`/`↓` should land.
 */
import { create } from 'zustand'

/** The two regions that take focus: the run list and the detail pane. */
export type FocusRegion = 'list' | 'detail'

export type Ui = {
  focus: FocusRegion
  setFocus: (focus: FocusRegion) => void
  /** `tab`: move focus to the other region. */
  toggleFocus: () => void
}

export const useUi = create<Ui>()((set) => ({
  focus: 'list',
  setFocus: (focus) => set({ focus }),
  toggleFocus: () =>
    set((state) => ({ focus: state.focus === 'list' ? 'detail' : 'list' })),
}))

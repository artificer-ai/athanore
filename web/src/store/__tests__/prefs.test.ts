import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  DEFAULT_LIST_WIDTH,
  FONT_SIZES,
  MIN_DETAIL_WIDTH,
  MIN_LIST_WIDTH,
  PREFS_STORAGE_KEY,
  applyFontSize,
  clampListWidth,
  syncFontSize,
  usePrefs,
} from '../prefs'

/** Whatever jsdom's window is; the clamp is derived from it. */
const VIEWPORT = window.innerWidth

function stored(): Record<string, unknown> {
  const raw = localStorage.getItem(PREFS_STORAGE_KEY)
  expect(raw).not.toBeNull()
  return (JSON.parse(raw as string) as { state: Record<string, unknown> }).state
}

describe('clampListWidth', () => {
  it('holds the mock defaults untouched', () => {
    expect(clampListWidth(DEFAULT_LIST_WIDTH, 1600)).toBe(DEFAULT_LIST_WIDTH)
  })

  it('clamps at the narrow end', () => {
    expect(clampListWidth(0, 1600)).toBe(MIN_LIST_WIDTH)
    expect(clampListWidth(-500, 1600)).toBe(MIN_LIST_WIDTH)
    expect(clampListWidth(MIN_LIST_WIDTH - 1, 1600)).toBe(MIN_LIST_WIDTH)
  })

  it('clamps at the wide end, leaving the detail pane its minimum', () => {
    expect(clampListWidth(9999, 1600)).toBe(1600 - MIN_DETAIL_WIDTH)
    expect(clampListWidth(1600, 1600)).toBe(1600 - MIN_DETAIL_WIDTH)
  })

  it('keeps the minimum when the viewport is too narrow for both bounds', () => {
    expect(clampListWidth(400, 500)).toBe(MIN_LIST_WIDTH)
    expect(clampListWidth(100, 300)).toBe(MIN_LIST_WIDTH)
  })

  it('rounds to whole pixels and refuses a non-number', () => {
    expect(clampListWidth(540.4, 1600)).toBe(540)
    expect(clampListWidth(Number.NaN, 1600)).toBe(DEFAULT_LIST_WIDTH)
  })
})

describe('usePrefs', () => {
  beforeEach(() => {
    localStorage.clear()
    usePrefs.setState({
      listWidth: DEFAULT_LIST_WIDTH,
      listCollapsed: false,
      autoSwitchOnRequest: true,
      notifications: false,
      token: null,
      fontSize: 'default',
    })
    delete document.documentElement.dataset.fontSize
  })

  it('starts on the defaults of the mock and 10 §Attention', () => {
    const state = usePrefs.getState()
    expect(state.listWidth).toBe(DEFAULT_LIST_WIDTH)
    expect(state.listCollapsed).toBe(false)
    // 10 §Attention: the pane switch is on by default and notifications
    // are opt-in.
    expect(state.autoSwitchOnRequest).toBe(true)
    expect(state.notifications).toBe(false)
    expect(state.token).toBeNull()
    // 21 §Type scale: the design's own base until the operator says
    // otherwise, and clearing site data comes back here.
    expect(state.fontSize).toBe('default')
  })

  it('clamps the width it is given', () => {
    usePrefs.getState().setListWidth(10)
    expect(usePrefs.getState().listWidth).toBe(MIN_LIST_WIDTH)

    usePrefs.getState().setListWidth(99999)
    expect(usePrefs.getState().listWidth).toBe(
      Math.max(MIN_LIST_WIDTH, VIEWPORT - MIN_DETAIL_WIDTH),
    )
  })

  it('persists every one of the six keys to localStorage', () => {
    const state = usePrefs.getState()
    state.setListWidth(400)
    state.toggleListCollapsed()
    state.setAutoSwitchOnRequest(false)
    state.setNotifications(true)
    state.setToken('op-token')
    state.setFontSize('large')

    expect(stored()).toEqual({
      listWidth: 400,
      listCollapsed: true,
      autoSwitchOnRequest: false,
      notifications: true,
      token: 'op-token',
      fontSize: 'large',
    })
  })

  it('does not persist the actions', () => {
    usePrefs.getState().setNotifications(true)
    expect(Object.keys(stored()).sort()).toEqual([
      'autoSwitchOnRequest',
      'fontSize',
      'listCollapsed',
      'listWidth',
      'notifications',
      'token',
    ])
  })
})

describe('a reload', () => {
  it('rehydrates the store from localStorage', async () => {
    localStorage.setItem(
      PREFS_STORAGE_KEY,
      JSON.stringify({
        state: {
          listWidth: 320,
          listCollapsed: true,
          autoSwitchOnRequest: false,
          notifications: true,
          token: 'kept',
          fontSize: 'xlarge',
        },
        version: 0,
      }),
    )

    // A fresh module registry is what a reload is: the store is built
    // again, and `persist` reads the browser's storage on the way up.
    vi.resetModules()
    const fresh = await import('../prefs')
    const state = fresh.usePrefs.getState()

    expect(state.listWidth).toBe(320)
    expect(state.listCollapsed).toBe(true)
    expect(state.autoSwitchOnRequest).toBe(false)
    expect(state.notifications).toBe(true)
    expect(state.token).toBe('kept')
    expect(state.fontSize).toBe('xlarge')
  })
})

describe('the font size on <html>', () => {
  beforeEach(() => {
    localStorage.clear()
    usePrefs.setState({ fontSize: 'default' })
    delete document.documentElement.dataset.fontSize
  })

  it('names the four steps of 21 §Type scale, smallest first', () => {
    expect([...FONT_SIZES]).toEqual(['small', 'default', 'large', 'xlarge'])
  })

  it('writes each step as data-font-size, and leaves the default off', () => {
    for (const step of FONT_SIZES) {
      applyFontSize(step)
      if (step === 'default') {
        // The absence of the attribute *is* the default, so an operator
        // who never opened the chooser and one who set it back are the
        // same document (21 §Type scale).
        expect(document.documentElement.hasAttribute('data-font-size')).toBe(false)
      } else {
        expect(document.documentElement.dataset.fontSize).toBe(step)
      }
    }
  })

  it('applies what the store already holds, before anything renders', () => {
    usePrefs.setState({ fontSize: 'large' })

    const stop = syncFontSize()

    expect(document.documentElement.dataset.fontSize).toBe('large')
    stop()
  })

  it('follows the store, and stops once it is unsubscribed', () => {
    const stop = syncFontSize()

    usePrefs.getState().setFontSize('xlarge')
    expect(document.documentElement.dataset.fontSize).toBe('xlarge')

    usePrefs.getState().setFontSize('default')
    expect(document.documentElement.hasAttribute('data-font-size')).toBe(false)

    stop()
    usePrefs.getState().setFontSize('small')
    expect(document.documentElement.hasAttribute('data-font-size')).toBe(false)
  })

  it('ignores a change to any other preference', () => {
    const stop = syncFontSize()
    usePrefs.getState().setFontSize('small')

    usePrefs.getState().setNotifications(true)

    expect(document.documentElement.dataset.fontSize).toBe('small')
    stop()
  })
})

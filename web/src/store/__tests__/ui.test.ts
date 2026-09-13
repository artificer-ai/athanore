import { beforeEach, describe, expect, it } from 'vitest'

import { useUi } from '../ui'

describe('useUi', () => {
  beforeEach(() => {
    useUi.setState({ focus: 'list', logComposerFor: null, focusedRun: null })
  })

  it('starts on the run list, where the first ↑↓ should land', () => {
    expect(useUi.getState().focus).toBe('list')
  })

  it('moves focus between the two regions', () => {
    useUi.getState().toggleFocus()
    expect(useUi.getState().focus).toBe('detail')

    useUi.getState().toggleFocus()
    expect(useUi.getState().focus).toBe('list')

    useUi.getState().setFocus('detail')
    expect(useUi.getState().focus).toBe('detail')
  })

  it('holds no run until `⏎` picks one up', () => {
    expect(useUi.getState().focusedRun).toBeNull()

    useUi.getState().focusRun('aaaa1111bbbb')
    expect(useUi.getState().focusedRun).toBe('aaaa1111bbbb')

    // A second pick-up replaces the first: one run is held at a time,
    // and the shell only ever offers it the selected one (D204 (2)).
    useUi.getState().focusRun('cccc3333dddd')
    expect(useUi.getState().focusedRun).toBe('cccc3333dddd')

    useUi.getState().blurRun()
    expect(useUi.getState().focusedRun).toBeNull()
  })

  it('keeps the held run and the focused region apart', () => {
    // `tab` moves the region; `⏎` picks a run up. Neither is the other,
    // and moving one must not move the other.
    useUi.getState().focusRun('aaaa1111bbbb')
    useUi.getState().toggleFocus()

    expect(useUi.getState().focus).toBe('detail')
    expect(useUi.getState().focusedRun).toBe('aaaa1111bbbb')
  })

  it('holds one log-composer request, named by its run', () => {
    expect(useUi.getState().logComposerFor).toBeNull()

    useUi.getState().focusLogComposer('a4c81f20b91e')
    expect(useUi.getState().logComposerFor).toBe('a4c81f20b91e')

    // A second ask replaces the first: there is one caret.
    useUi.getState().focusLogComposer('cccc3333dddd')
    expect(useUi.getState().logComposerFor).toBe('cccc3333dddd')

    useUi.getState().clearLogComposer()
    expect(useUi.getState().logComposerFor).toBeNull()
  })

  it('is transient: nothing of it reaches localStorage', () => {
    localStorage.clear()
    useUi.getState().setFocus('detail')
    useUi.getState().toggleFocus()
    useUi.getState().focusRun('aaaa1111bbbb')
    useUi.getState().blurRun()
    expect(localStorage.length).toBe(0)
  })
})

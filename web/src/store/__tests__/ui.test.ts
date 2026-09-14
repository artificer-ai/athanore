import { beforeEach, describe, expect, it } from 'vitest'

import { useUi } from '../ui'

describe('useUi', () => {
  beforeEach(() => {
    useUi.setState({ focus: 'list', logComposerFor: null })
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
    useUi.getState().focusLogComposer('aaaa1111bbbb')
    useUi.getState().clearLogComposer()
    expect(localStorage.length).toBe(0)
  })
})

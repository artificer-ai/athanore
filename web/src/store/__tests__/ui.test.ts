import { beforeEach, describe, expect, it } from 'vitest'

import { useUi } from '../ui'

describe('useUi', () => {
  beforeEach(() => {
    useUi.setState({ focus: 'list' })
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

  it('is transient: nothing of it reaches localStorage', () => {
    localStorage.clear()
    useUi.getState().setFocus('detail')
    useUi.getState().toggleFocus()
    expect(localStorage.length).toBe(0)
  })
})

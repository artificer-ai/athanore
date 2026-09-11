import { describe, expect, it } from 'vitest'

import { OVERLAYS, validateAppSearch } from '../search'

describe('validateAppSearch', () => {
  it('keeps every key it recognises', () => {
    expect(
      validateAppSearch({
        run: '01JD5',
        pane: 2,
        overlay: 'palette',
        task: 7,
        node: 'engineering',
        action: 'gamedev:override',
      }),
    ).toEqual({
      run: '01JD5',
      pane: 2,
      overlay: 'palette',
      task: 7,
      node: 'engineering',
      action: 'gamedev:override',
    })
  })

  it('accepts every overlay of 10 §Overlays', () => {
    for (const overlay of OVERLAYS) {
      expect(validateAppSearch({ overlay })).toEqual({ overlay })
    }
  })

  it('drops an unknown overlay rather than throwing', () => {
    // A bookmark from a build that still had the CRT chrome (D71).
    expect(() => validateAppSearch({ overlay: 'crt' })).not.toThrow()
    expect(validateAppSearch({ overlay: 'crt', run: 'a4c8' })).toEqual({ run: 'a4c8' })
    expect(validateAppSearch({ overlay: 3 })).toEqual({})
    expect(validateAppSearch({ overlay: '' })).toEqual({})
  })

  it('parses numeric keys out of strings, as a hand-typed URL gives them', () => {
    expect(validateAppSearch({ pane: '4', task: '12' })).toEqual({ pane: 4, task: 12 })
  })

  it('drops numbers that are not indices', () => {
    expect(validateAppSearch({ pane: -1 })).toEqual({})
    expect(validateAppSearch({ pane: 1.5 })).toEqual({})
    expect(validateAppSearch({ pane: 'two' })).toEqual({})
    expect(validateAppSearch({ pane: '' })).toEqual({})
    expect(validateAppSearch({ pane: Number.NaN })).toEqual({})
    // Task ids start at 1.
    expect(validateAppSearch({ task: 0 })).toEqual({})
    expect(validateAppSearch({ task: -3 })).toEqual({})
  })

  it('keeps the narrow global screen’s index, and drops what is not one', () => {
    // `?global=` is the global cycle's own index, present while that
    // screen is up (21 §Narrow layout, D216): parsed exactly as `pane`
    // is, and a string from a hand-typed URL is fine.
    expect(validateAppSearch({ global: 0 })).toEqual({ global: 0 })
    expect(validateAppSearch({ global: '2' })).toEqual({ global: 2 })
    expect(validateAppSearch({ run: 'a4c8', pane: 1, global: 0 })).toEqual({
      run: 'a4c8',
      pane: 1,
      global: 0,
    })
    expect(validateAppSearch({ global: -1 })).toEqual({})
    expect(validateAppSearch({ global: 0.5 })).toEqual({})
    expect(validateAppSearch({ global: 'inbox' })).toEqual({})
    expect(validateAppSearch({ global: '' })).toEqual({})
  })

  it('drops a run id that is not a non-empty string', () => {
    expect(validateAppSearch({ run: '' })).toEqual({})
    expect(validateAppSearch({ run: '   ' })).toEqual({})
    expect(validateAppSearch({ run: 42 })).toEqual({})
  })

  it('drops a node filter that is not a non-empty string', () => {
    expect(validateAppSearch({ node: '' })).toEqual({})
    expect(validateAppSearch({ node: '   ' })).toEqual({})
    expect(validateAppSearch({ node: 3 })).toEqual({})
  })

  it('drops an action id that is not a non-empty string', () => {
    // Opaque like `run` and `node`: which actions exist is the installed
    // workflows' business, and the overlay says so when there is no such
    // one (T070).
    expect(validateAppSearch({ action: '' })).toEqual({})
    expect(validateAppSearch({ action: '   ' })).toEqual({})
    expect(validateAppSearch({ action: 7 })).toEqual({})
  })

  it('ignores keys it does not know', () => {
    expect(validateAppSearch({ crt: true, priority: 4 })).toEqual({})
  })

  it('drops nothing when the search is empty', () => {
    expect(validateAppSearch({})).toEqual({})
  })
})
